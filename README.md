# StreamDock

在 macOS 上将本地视频拼接播放到 Mirabox M18 的 **15 个按键屏**，也可单键播放或导出离线预览。当前适配目标为 **M18V25E**，所有播放均无音频。

支持片段播放、循环、底部按键暂停与跳转，以及按键间距补偿。设备画面效果仍待实机确认，验证范围见[开发指南](docs/development.md#硬件验证范围)。

## 使用示例

完成下方安装后，在仓库根目录执行。将 `/path/to/video.mp4` 替换为自己的本地视频路径，路径含空格时保留引号。

```sh
# 无需连接设备：导出从第 30 秒开始的 5 秒拼接预览
uv run streamdock play "/path/to/video.mp4" --start 30 --seconds 5 --preview previews/video.mp4
open previews/video.mp4

# 连接设备后：在全部按键屏播放 10 秒
uv run streamdock play "/path/to/video.mp4" --seconds 10

# 循环播放完整视频；Ctrl+C 停止
uv run streamdock play "/path/to/video.mp4" --loop

# 只在第 8 个逻辑按键上播放
uv run streamdock play "/path/to/video.mp4" --key 8 --fps 15
```

预览成功后输出 `预览已保存：<输出文件的绝对路径>`。设备播放正常结束后输出 JSON 统计，包含已发送帧数 `sent_frames`、丢弃帧数 `dropped_frames` 和循环重启次数 `loops`。

## 安装与连接

需要 Python 3.11+、[uv](https://docs.astral.sh/uv/) 和包含 `ffmpeg`、`ffprobe` 的 [FFmpeg](https://ffmpeg.org/)。预览导出还需要 FFmpeg 支持 `libx264` 编码器。以下命令均在仓库根目录执行。

```sh
# macOS 使用 Homebrew 安装 FFmpeg
brew install ffmpeg
uv sync --locked
```

官方 SDK 和配套原生通信库已随项目提供，完成上述安装后即可连接设备。源码和 wheel 均包含 SDK，无需单独下载或设置路径。上游同步流程见[开发指南](docs/development.md#官方-sdk-版本管理)。

通过 USB 连接 M18，退出可能同时更新按键画面的 Mirabox StreamDock 软件，再检查设备：

```sh
uv run streamdock devices
```

命令输出设备 JSON 数组；`[]` 表示未枚举到设备，`playback_supported: true` 表示支持播放。多台 M18 同时连接时，使用 `--serial` 指定其中一台。SDK 随 Python 包加载，不依赖当前工作目录。

## 播放控制

| 底部无屏按键 | 操作 |
| --- | --- |
| 左 | 快退 10 秒 |
| 中 | 暂停 / 继续 |
| 右 | 快进 10 秒 |

暂停时仍可跳转，显示目标位置的一帧后保持暂停。跳转范围限于当前视频或指定片段；按住按键只触发一次。Ctrl+C 停止播放并释放连接。

默认以 10 fps 将画面等比缩放、补黑边后，拼接到 5×3 个 64×64 按键屏。完整参数、逻辑按键编号、间距调整和缓存操作见[使用指南](docs/usage.md)。

## 使用前须知

- 仅接收本地视频文件，格式取决于本机 FFmpeg；不提供默认视频或自动下载。
- 播放会覆盖所选按键的画面，停止后不恢复原图标，可重新打开官方软件恢复页面；程序不主动修改亮度、LED 或背景图。
- 首次设备播放会先缓存**整段视频**，即使只播放一个片段；想直接开始实时解码可用 `--no-cache`。缓存不会自动清理，管理方法见[视频缓存](docs/usage.md#视频缓存)。
- 实际帧率受 USB 和设备吞吐量限制；发送较慢时跳过过期帧，避免延迟累积。
- 预览不模拟 JPEG 压缩或 USB 速度，已有输出文件不会被覆盖。

## 开发与文档

- [使用指南](docs/usage.md)：命令参数、间距补偿、缓存管理与常见问题。
- [开发指南](docs/development.md)：开发验证、代码结构、硬件适配与缓存实现。
