# 固定弹幕标签体系 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每条弹幕增加受约束的两层主题和质量标签，并让报告只按七种固定报告主题聚合。

**Architecture:** `MessageLabel` 定义新增标签的数据契约；Codex Schema、提示词、缓存与 CSV 从它派生。分析层保留 `raw_topic` 以供追溯、按 `report_topic` 聚合；工作簿呈现归并后的明细与图表。

**Tech Stack:** Python 3.12、Pydantic、pytest、openpyxl、Codex CLI。

**Spec:** `docs/superpowers/specs/2026-09-22-fixed-chat-label-taxonomy-design.md`

## Global Constraints

- 报告主题：游戏内容、直播体验、主播表现、观众互动、技术问题、角色或剧情、其他。
- 内容类型：游戏内容、直播互动、主播内容、技术与平台、日常话题、社区文化、其他。
- 消息类型：评价反馈、提问求助、信息陈述、玩笑梗图、表情或刷屏、机器人通知、其他。
- 置信度：高、中、低；`is_bot` 与 `needs_review` 为布尔值。
- 汇总、趋势和图表只使用 `report_topic`；原始主题仅供审计。
- 不修改原始输入、既有结果文件或音频转写项目。

## Review Focus

- 枚举外的 Codex 输出必须被拒绝。（Task 1）
- 旧 CSV 的 `topic` 必须作为原始主题保留，报告主题为“其他”。（Task 2）
- 不同原始主题相同报告主题必须汇总为一行。（Task 2）
- 机器人信息必须使用 `is_bot=true` 和“机器人通知”。（Task 1）
- 图表类别必须是报告主题。（Task 3）

---

### Task 1: 扩展标注契约与 Codex 响应验证

**Files:** Modify `src/twitch_chat_workflow/models.py`, `src/twitch_chat_workflow/providers.py`, `src/twitch_chat_workflow/labeling.py`, `tests/test_codex_provider.py`, `tests/test_labeling.py`.

**Interfaces:** Produces `MessageLabel` with `raw_topic`, `report_topic`, `content_type`, `message_type`, `is_bot`, `needs_review`, `confidence`; `CodexSessionProvider.label()` rejects missing或枚举外字段。

- [ ] **Step 1: Write failing tests.** Add a valid complete label assertion and parameterized `report_topic="脚趾处理"` / `confidence="很高"` rejection cases in `test_codex_provider.py`; add CSV/batch field assertions in `test_labeling.py`.
- [ ] **Step 2: Verify RED.** Run `pytest tests/test_codex_provider.py tests/test_labeling.py -v`; expect failures because current schema lacks the new fields.
- [ ] **Step 3: Implement minimal contract.** Add Pydantic `Literal` fields with exact enum values; replace old `topic` in JSON Schema; prompt Codex to choose only the seven report topics and set `needs_review=true` when uncertain; serialize all fields to batch JSON and `labeled_chat.csv`.
- [ ] **Step 4: Verify GREEN.** Run `pytest tests/test_codex_provider.py tests/test_labeling.py -v`; expect PASS for schema rejection and cache round trips.
- [ ] **Step 5: Commit.** Run `git add src/twitch_chat_workflow/models.py src/twitch_chat_workflow/providers.py src/twitch_chat_workflow/labeling.py tests/test_codex_provider.py tests/test_labeling.py`; then `git commit -m "feat: constrain semantic chat labels"`.

### Task 2: 以报告主题归并分析数据

**Files:** Modify `src/twitch_chat_workflow/analysis.py`, `tests/test_analysis.py`.

**Interfaces:** Consumes new CSV rows or legacy `topic` rows; produces summaries/trends keyed by `report_topic`, while labels/quotes retain both topic layers.

- [ ] **Step 1: Write failing tests.** Add rows `raw_topic="撞脚趾"` and `raw_topic="脚趾处理"`, both `report_topic="其他"`, assert a single two-message report summary; add legacy `topic="旧主题"` assertion for `raw_topic="旧主题"` and `report_topic="其他"`.
- [ ] **Step 2: Verify RED.** Run `pytest tests/test_analysis.py -v`; expect failure because current code groups on `topic`.
- [ ] **Step 3: Implement minimal grouping.** Normalize `raw_topic` from `raw_topic` or legacy `topic`, normalize missing report topic to “其他”, reject invalid report topics, and rename analysis summary/trend fields to `report_topic`.
- [ ] **Step 4: Verify GREEN.** Run `pytest tests/test_analysis.py -v`; expect PASS with deterministic report-topic grouping and legacy compatibility.
- [ ] **Step 5: Commit.** Run `git add src/twitch_chat_workflow/analysis.py tests/test_analysis.py`; then `git commit -m "feat: aggregate chat by fixed report topic"`.

### Task 3: 更新工作簿字段、图表和说明

**Files:** Modify `src/twitch_chat_workflow/workbook.py`, `tests/test_workbook.py`, `README.md`.

**Interfaces:** Consumes new `AnalysisTables` fields; produces the same four sheets with audit fields and report-topic-only charts.

- [ ] **Step 1: Write failing tests.** Assert 标签明细 headers include 原始主题、报告主题、内容类型、消息类型、是否机器人、是否需要人工复核、置信度; assert 主题 `A1` is 报告主题 and the chart category reference uses that column.
- [ ] **Step 2: Verify RED.** Run `pytest tests/test_workbook.py -v`; expect failure because the old exporter has one topic column.
- [ ] **Step 3: Implement minimal export.** Add the audit columns with Chinese 是/否 rendering, add both topic layers to 原话, and make 主题 summary, lower trend table, and Top 10 chart use `report_topic`; preserve sheet names, filters, and formula-injection protections.
- [ ] **Step 4: Verify GREEN.** Run `pytest tests/test_workbook.py -v && pytest -q`; expect the workbook and complete test suite to pass.
- [ ] **Step 5: Commit.** Update README field definitions; run `git add src/twitch_chat_workflow/workbook.py tests/test_workbook.py README.md`; then `git commit -m "feat: export fixed chat taxonomy report"`.

### Task 4: Sayu 小样本真实回归

**Files:** Read `D:/主播分析结果/弹幕数据/Sayu/02_弹幕/twitchchatdownloader_first_option.csv`; generate only `D:/twitch-chat-workflow/results/Sayu_codex_trial_fixed_taxonomy/`.

**Interfaces:** Consumes 120 条 Sayu 弹幕与当前 Codex 登录态；produces包含所有新增字段的 `弹幕分析.xlsx`。

- [ ] **Step 1: Create independent output.** Create `D:\twitch-chat-workflow\results\Sayu_codex_trial_fixed_taxonomy` and stage the first 120 source rows without modifying the source CSV.
- [ ] **Step 2: Run all stages.** With `PYTHONPATH=src` and `D:\anaconda3\python.exe`, run clean, label, and aggregate using the trial config; use the approved external Codex execution context.
- [ ] **Step 3: Verify workbook.** Load the XLSX and assert the four prescribed sheet names, `报告主题` in 主题 headers, the seven report topics only, and exactly one chart on each chart sheet.
- [ ] **Step 4: Commit source only.** Commit source/tests/docs changes using `git add README.md src tests docs/superpowers` and `git commit -m "test: verify fixed taxonomy with Sayu sample"`; never commit generated CSV, JSON, state, batch, or XLSX files.
