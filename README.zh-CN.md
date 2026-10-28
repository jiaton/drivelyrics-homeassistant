# DriveLyrics Home Assistant 集成

让 [DriveLyrics](https://drivelyrics.com) 显示 Home Assistant 里**车的媒体播放器**正在放的歌的同步歌词——车机屏幕、手机、任何浏览器都行。为特斯拉（Tesla Fleet、Teslemetry、Tessie）的媒体播放器设计，任何 `media_player` 都能用。不需要 Spotify 账号：车上放的 Spotify、Apple Music、蓝牙、电台都可以。

## 安装

[![在 HACS 中打开本仓库](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jiaton&repository=drivelyrics-homeassistant&category=integration)

1. 点上面的按钮（或在 HACS 里：⋮ → 自定义存储库 → 添加 `https://github.com/jiaton/drivelyrics-homeassistant`，类型选 Integration），**下载**，然后重启 Home Assistant。
2. [![添加 DriveLyrics 集成](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=drivelyrics)，或 设置 → 设备与服务 → 添加集成 → DriveLyrics。
3. 选媒体播放器。（Tesla Fleet 默认把车的媒体播放器关着，集成会提示帮你打开。）
4. 点 **打开网站**，登录 DriveLyrics，确认码一致，点 **同意**。Home Assistant 会自己完成。

不用复制令牌，不用写 YAML，也不用把 Home Assistant 暴露到公网。

## 工作原理与费用

DriveLyrics 决定什么时候需要知道正在放什么（打开歌词页、一首歌刚结束、点了刷新），通过 Home Assistant 主动连过去的长连接来问。每问一次，集成让车的集成读一次车，再把歌名、歌手、专辑、时长、进度发回去；没有歌词页开着就什么都不问。

- **费用**：特斯拉每次回答是一次 Fleet API `vehicle_data` 请求（特斯拉按次计费），歌词页开着时大约每首歌一次。DriveLyrics 设置里有每月预算和每小时上限。
- **隐私**：集成拿到的钥匙只能发送正在播放、接收更新请求。删除集成会同时删除这把钥匙；在 DriveLyrics（设置 → 推送通道）删除钥匙，Home Assistant 会提示重新关联。
- **其他播放器**：会自己报告变化的播放器（Sonos、Music Assistant 等），歌词页开着时换歌会立即发送；这类播放器可以在集成选项里关掉「每次回应前先刷新播放器」。

更多说明见 [English README](README.md)。
