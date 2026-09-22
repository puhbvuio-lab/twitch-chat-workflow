# Twitch 弹幕工作流

这是一个独立运行的 Twitch VOD 弹幕处理工具，可完成弹幕获取、清洗、可选语义标注和趋势聚合。它不会下载或分析视频、音频，也不依赖其他同级项目。

## 环境与安装

需要 Python 3.11 或更高版本。安装项目及测试依赖：

```powershell
python -m pip install -e ".[dev]"
```

如需从 Twitch 获取弹幕，还需安装可选的下载依赖：

```powershell
python -m pip install -e ".[acquisition]"
```

## 配置任务

复制 `examples/job.json`，替换其中的 VOD URL，并选择输出目录。主要配置字段如下：

- `vod_url`：必填，Twitch VOD 地址。
- `start_seconds`、`end_seconds`：可选，只处理指定时间范围内的弹幕。
- `output_dir`：任务输出根目录。
- `cookies_from_browser`：可选，浏览器 Cookie 来源，例如 `chrome` 或 `edge`。
- `aggregation.interval_seconds`：趋势聚合时间间隔，默认为 60 秒；支持包括 1 秒在内的任意正整数秒。
- `labeling.enabled`：是否启用语义标注。要生成最终分析工作簿必须设为 `true`。
- `labeling.codex_command`：Codex CLI 命令路径，默认为 `codex`。
- `labeling.timeout_seconds`：单批 Codex 调用超时时间。

`cookies_from_browser` 只在程序运行时传给下载适配器，不会写入任务配置快照或错误记录。请勿在 JSON 配置中填写 Cookie 内容、访问令牌或其他密钥。

## 运行工作流

可以单独运行某个可重试阶段，也可以按顺序运行完整流程：

```powershell
python -m twitch_chat_workflow acquire --config job.json
python -m twitch_chat_workflow clean --config job.json
python -m twitch_chat_workflow label --config job.json
python -m twitch_chat_workflow aggregate --config job.json
python -m twitch_chat_workflow run --config job.json
```

各命令用途：

- `acquire`：下载并保存原始弹幕。
- `clean`：规范时间和文本、修复可确认的乱码并去除完全重复记录。
- `label`：在启用时为弹幕添加语义标签。
- `aggregate`：按设定的时间间隔生成弹幕趋势。
- `run`：依次执行上述全部阶段；任一阶段失败后停止。

## 输出与断点续跑

每个任务写入独立的 `<output_dir>/<job_id>/` 目录，主要产物包括：

- `01_raw_chat/`：下载器返回的原始 JSONL 弹幕。
- `02_clean_chat/`：规范化 CSV、被排除记录和修复统计。
- `03_labeled_chat/`：可选的逐条语义标签及批次结果。
- `04_chat_trends/`：按时间窗口聚合的 `弹幕趋势.csv`、`弹幕趋势.json` 和最终 `弹幕分析.xlsx`。
- `09_status/`：各阶段的状态、输入指纹和错误摘要。

清洗和标注不会覆盖原始弹幕。只有当脱敏后的配置、输入指纹和预期产物都与上次完成时一致，程序才会跳过已完成阶段；输入变化、产物缺失或批次失败都会安全重跑。

将 `aggregation.interval_seconds` 设为 `1` 可生成一秒一个窗口的趋势数据。没有弹幕的窗口仍会输出零值指标，同时逐条弹幕保留原始小数秒和 `timestamp_ms` 精度。

## 语义标注说明

语义标注使用当前机器已保存的 Codex CLI 登录态。项目通过 `codex exec --ephemeral` 批量请求结构化标签，不读取或保存 `auth.json`、访问令牌或 API Key。运行前请确认终端中的 `codex` 命令已经登录。

每个批次必须返回与输入完全一致的 `message_id` 顺序、情绪、主题和兴趣信号。批次失败、Codex 未登录、超时或返回结构不合规时，标注阶段会保留可重试状态，不会把失败结果伪装成中性标签，也不会生成不完整的 Excel。

## Excel 分析工作簿

标注全部成功后，`aggregate` 和 `run` 会生成 `04_chat_trends/弹幕分析.xlsx`，包含四个工作表：

- `标签明细`：逐条弹幕的清洗文本、原话、情绪、主题、兴趣信号和标注批次。
- `情绪趋势`：按 `aggregation.interval_seconds` 分桶的正面/中性/负面数量和占比，并附占比折线图。
- `主题`：主题数量汇总、情绪分布、代表性原话、时间窗口 × 主题趋势，并附主题 Top 10 柱状图。
- `原话`：按时间排序的原话、用户、主题、情绪和消息 ID，便于人工回看。

工作簿只在所有标签批次成功后原子生成；已有完整文件不会被失败运行覆盖。

本项目只处理 VOD 弹幕，不负责下载媒体、检查视频、分析音频、生成 CCV/历史数据或制作 Excel 报告。

## 测试

测试使用离线替身，不会访问 Twitch 或模型服务：

```powershell
$env:PYTHONPATH = 'src'
python -m pytest -q
```
