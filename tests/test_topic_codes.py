import json

import pytest

from twitch_chat_workflow.models import ChatMessage
from twitch_chat_workflow.providers import (
    CodexSessionProvider, ExternalApiProvider, _label_schema, parse_label_response,
)


CASES = [
    ('game_cinematic', '游戏影响', '剧情与世界观', '电影化过场/演出高光'),
    ('game_narrative', '游戏影响', '剧情与世界观', '剧情内容/叙事情绪'),
    ('game_worldview', '游戏影响', '剧情与世界观', '整体剧情世界观感受'),
    ('game_boss', '游戏影响', '战斗体验', 'BOSS战'),
    ('game_combat', '游戏影响', '战斗体验', '常规战斗'),
    ('game_combat_overall', '游戏影响', '战斗体验', '综合战斗感受'),
    ('game_movement', '游戏影响', '探索与互动', '跑图与移动'),
    ('game_puzzle', '游戏影响', '探索与互动', '调查与解谜'),
    ('game_character', '游戏影响', '其他整体兴趣', '角色兴趣'),
    ('game_art_audio', '游戏影响', '其他整体兴趣', '整体美术与音声兴趣'),
    ('game_interest', '游戏影响', '其他整体兴趣', '游戏整体兴趣'),
    ('game_other', '游戏影响', '其他', '其他'),
    ('non_game_streamer', '非游戏影响', '主播表现', '主播表现'),
    ('non_game_audience', '非游戏影响', '观众互动', '观众互动'),
    ('non_game_technical', '非游戏影响', '技术与直播质量', '技术与直播质量'),
    ('non_game_bot', '非游戏影响', '系统与机器人', '系统与机器人'),
    ('non_game_life', '非游戏影响', '生活闲聊', '生活闲聊'),
    ('non_game_other', '非游戏影响', '其他非游戏内容', '其他非游戏内容'),
    ('undetermined', '无法判断', '其他', '其他'),
]


def payload(code):
    return dict(message_id='m1', sentiment='neutral', raw_topic='原话细节', topic_code=code,
                content_type='其他', message_type='其他', is_bot=False,
                needs_review=True, confidence='低', interest_signal=False)


@pytest.mark.parametrize('code,direction,primary,secondary', CASES)
def test_code_expands_to_exact_hierarchy(code, direction, primary, secondary):
    label = parse_label_response(json.dumps({'labels': [payload(code)]}), ['m1'])[0]
    assert (label.impact_direction, label.primary_module, label.secondary_module) == (direction, primary, secondary)
    assert label.needs_review is True
    assert label.confidence == '低'
    assert label.raw_topic == '原话细节'


@pytest.mark.parametrize('code', ['音乐与音效', 'GAME_BOSS', '', None, 1])
def test_invalid_code_is_not_silently_other(code):
    with pytest.raises(RuntimeError, match='label schema') as error:
        parse_label_response(json.dumps({'labels': [payload(code)]}), ['m1'])
    assert error.value.validation_errors


def test_schema_requires_only_code_not_model_generated_hierarchy():
    item = _label_schema()['properties']['labels']['items']
    assert set(item['properties']['topic_code']['enum']) == {row[0] for row in CASES}
    assert 'topic_code' in item['required']
    assert not {'impact_direction', 'primary_module', 'secondary_module'} & set(item['properties'])


def test_code_cannot_be_combined_with_conflicting_hierarchy():
    row = payload('game_boss')
    row.update(impact_direction='无法判断', primary_module='其他', secondary_module='其他')
    with pytest.raises(RuntimeError, match='label schema'):
        parse_label_response(json.dumps({'labels': [row]}), ['m1'])


@pytest.mark.parametrize('kind', ['codex', 'external'])
def test_provider_maps_code_and_supplies_complete_dictionary(kind):
    response = json.dumps({'labels': [payload('game_art_audio')]})
    prompts = []

    def runner(command, prompt, timeout):
        prompts.append(prompt)
        return response

    def transport(method, url, headers, body, timeout):
        prompts.append(json.loads(body)['messages'][0]['content'])
        return 200, json.dumps({'content': [{'type': 'text', 'text': response}]})

    provider = (CodexSessionProvider(runner=runner) if kind == 'codex' else
                ExternalApiProvider(base_url='https://example.invalid', api_key='test', transport=transport))
    label = provider.label([ChatMessage(message_id='m1', timestamp_seconds=0,
                                       text='音乐真好听', original_text='音乐真好听')])[0]
    assert label.secondary_module == '整体美术与音声兴趣'
    assert label.primary_module == '其他整体兴趣'
    for code, direction, primary, secondary in CASES:
        assert f'{code}: {direction} > {primary} > {secondary}' in prompts[0]
