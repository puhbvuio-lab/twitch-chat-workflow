# Twitch Chat Workflow：设计规格

## 目标与边界

这是一个可独立复制和运行的 Twitch 弹幕处理项目。它从 Twitch VOD URL 获取弹幕，保留原始数据，并输出时间标准化、可复核、可选语义标注的弹幕产物。

项目**不**下载视频、不提取音轨、不进行语音转写、不生成 CCV 或视觉分析，也不依赖 `D:\主播基础分析` 或 `D:\twitch-video-chat-analysis` 的运行时代码。

成功标准：给定一个 VOD URL（及可选开始/结束秒数），可断点续跑地得到原始弹幕、清洗弹幕、可选语义标签和按时间桶聚合的趋势数据；任何一步的状态、输入和错误都可追溯。

## 输入与输出

### 输入

- 必填：`vod_url`。
- 可选：`start_seconds`、`end_seconds`、`output_dir`、浏览器 Cookie 来源（`chrome` / `edge` / 禁用）。
- 可选标注配置：`enabled`、`provider`、`fallback_provider`、模型、批大小、并发数、上下文条数。
- 时间桶大小：默认 60 秒，要求为正整数秒。

### 输出目录

每个任务位于 `<output_dir>/<job_id>/`：

- `01_raw_chat/`：下载器原始弹幕文件与下载元数据；永不被清洗步骤覆盖。
- `02_clean_chat/`：UTF-8 清洗 CSV、被剔除行 CSV 与修复统计 JSON。
- `03_labeled_chat/`：逐消息标签 CSV、批次响应 JSON、语义标注状态文件。
- `04_chat_trends/`：按时间桶的消息量、用户数、情绪、主题和兴趣信号 CSV/JSON。
- `09_status/`：阶段状态、配置快照、日志与错误摘要。

## 架构

### 核心模块

1. `acquisition`：通过可替换下载适配器获取 VOD 弹幕；默认适配 TwitchChatDownloader。Cookie 仅传给需要登录的下载调用，不写入配置快照或日志。
2. `normalization`：验证字段、解析/统一时间、修复常见乱码、保留原文、去除完全重复记录，并明确记录被排除原因。
3. `labeling`：按稳定排序后的消息批处理。首选 `codex_session`，不可用时可回退 `openai_responses`；无标注配置时完全跳过该阶段。标签必须包含可审计的来源、模型、批次号与原始消息 ID。
4. `aggregation`：只使用清洗或已标注的弹幕生成时间桶趋势；空桶照实输出零，不补造消息或情绪。
5. `state`：每个阶段都以原子状态文件保存 `pending/running/completed/failed/skipped`、输入指纹、产物清单及错误摘要。输入指纹一致且产物完整时允许跳过已完成阶段。
6. `cli`：提供分阶段命令与总入口；CLI 仅编排模块，不包含业务逻辑。

### 命令接口

```text
python -m twitch_chat_workflow acquire --config job.json
python -m twitch_chat_workflow clean --config job.json
python -m twitch_chat_workflow label --config job.json
python -m twitch_chat_workflow aggregate --config job.json
python -m twitch_chat_workflow run --config job.json
```

`run` 顺序执行 acquire → clean → label（若启用）→ aggregate；任一失败时停止后续阶段。各子命令可独立重试。

## 数据与错误处理原则

- 原始弹幕不可变；清洗和标签均生成新文件。
- 每条标准化消息使用相对 VOD 秒数、ISO 时间（若源数据提供）和稳定消息 ID。
- 仅修复可确定的编码错误；无法确定的文本保留原文并记录 `encoding_warning`，不擅自猜测。
- 去重键为可配置的稳定字段组合；默认不按“文字相同”直接去重，避免删除不同用户的相同弹幕。
- 标注失败的单个批次可重试，并在总状态中明确列出；不将失败批次伪装为无情绪/无主题。
- 下载、网络、认证、模型和格式错误分别归类；错误信息不输出 Cookie 或密钥。

## 测试与验收

- 单元测试：时间解析、乱码修复、去重、窗口聚合、配置验证、状态恢复。
- 适配器测试：使用录制的脱敏响应，不访问真实 Twitch 或模型服务。
- 端到端烟雾测试：从 fixture 原始弹幕到趋势 CSV/JSON。
- 验收检查：两个项目之间无 Python import、无相对路径依赖、无共享输出目录；复制本项目目录并安装其自身依赖后可运行。
