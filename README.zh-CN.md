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

- **隐私**：集成拿到的钥匙只能发送正在播放、接收更新请求。删除集成会同时删除这把钥匙；在 DriveLyrics（设置 → 推送通道）删除钥匙，Home Assistant 会提示重新关联。
- **其他播放器**：会自己报告变化的播放器（Sonos、Music Assistant 等），歌词页开着时换歌会立即发送；这类播放器可以在集成选项里关掉「每次回应前先刷新播放器」。

## 上限与费用

特斯拉每次回答是一次 Fleet API 读车请求（vehicle data），每次 0.002 美元（1 美元 500 次），特斯拉每月抵扣 10 美元（5000 次）。放歌时开着歌词页每小时大约 15–20 次；没有歌词页开着就是 0 次。

两道上限，都可以自己改：

- **DriveLyrics 里**（设置 → 推送通道）：每月预算（默认 800 次）和每小时次数，决定 DriveLyrics 什么时候来问。
- **Home Assistant 里**（这个集成的选项）：**每小时读车次数上限**（默认 60 次，切歌、刷新时一下子最多 20 次）和 **每月读车次数上限**（默认 1000 次）。这是你自己这边的锁：不管 DriveLyrics 怎么要求，Home Assistant 读车都不会超过它；默认值把大部分特斯拉免费额度留给 Home Assistant 自己用。

到了上限不会悄悄停掉：DriveLyrics 收到 Home Assistant 已有的信息（不读车、不花钱），并在屏幕上注明；**读车上限** 传感器显示当前状态；修复中心提示一次（每小时上限：每设一次上限提示一次；每月上限：每月一次），不会每次都弹。**本月读车次数** 记录每一次读车。

更多说明见 [English README](README.md)。
