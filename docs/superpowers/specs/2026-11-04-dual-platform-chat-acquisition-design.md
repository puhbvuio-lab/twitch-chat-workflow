# Twitch/YouTube 双平台弹幕采集设计

## 意图

将仅支持 Twitch VOD 的工作流扩展为 Twitch 与 YouTube 直播回放共用的采集、清洗、语义标注、聚合和 Excel 输出工具。用户提供视频 URL，默认自动识别平台，也可显式指定平台。

## 目标

- 保持现有 Twitch 任务配置和断点续跑兼容。
- 支持 youtube.com/watch 与 youtu.be 回放地址。
- YouTube 使用 yt-dlp 下载 live_chat 回放，并支持浏览器 Cookie。
- 两个平台统一产出 RawMessage，复用下游处理。
- 无法识别、平台冲突、无聊天回放或下载失败时明确报错。

## 非目标

- 不分析视频、音频、CCV 或频道历史。
- 不实现直播中的持续监听，只处理可获取的直播/首映聊天回放。
- 不采集普通评论区评论。
- 不改变标签体系或分析工作簿结构。

## 约束

- Python 3.11+。
- platform 为 auto、twitch 或 youtube，默认 auto。
- Twitch 继续使用 twitch-chat-downloader；YouTube 使用 yt-dlp。
- Cookie 只作为运行时设置，不进入配置快照。

## 方案比较

### 方案一：一个通用库处理两个平台

代码最少，但 chat-downloader 的 YouTube 回放存在已知兼容问题，也会改变稳定的 Twitch 路径。

### 方案二：平台适配器加 URL 路由（采用）

保留 Twitch 适配器，新增 yt-dlp YouTube 适配器，统一返回 RawMessage。改动集中、可独立测试，并复用已验证的 live_chat JSONL 格式。

### 方案三：直接并入临时 YouTube 脚本

短期可用，但会把下载、转换和任务编排耦合，不利于重试和维护。

## 设计

- JobConfig.platform 表示期望平台，默认 auto。
- detect_platform(vod_url) 只接受明确的 Twitch 或 YouTube 视频主机与路径。
- build_chat_downloader(config) 在 CLI 中选择适配器；平台与 URL 冲突时在网络请求前失败。
- YouTubeChatDownloaderAdapter 通过当前 Python 解释器执行 yt-dlp，在临时目录下载 live_chat JSONL，解析文本、表情、付费留言、贴纸和会员消息，按消息 ID 去重，再按秒数过滤。
- TwitchChatDownloaderAdapter 保持现有行为。
- 下载依赖按平台拆分，并提供包含两者的 acquisition extra。
- README 和示例任务改为双平台说明。

## 验证

- URL 自动识别和显式冲突测试。
- Twitch 旧配置兼容测试。
- YouTube JSONL 解析、富文本、付费消息、去重和时间范围测试。
- yt-dlp 参数和 Cookie 参数测试，不访问真实网络。
- CLI 路由与全量离线测试。
- 使用公开聊天回放做真实采集烟雾测试，不运行模型标注。
