# 使用指南

[返回 README](../README.md) · [开发指南](development.md)

安装依赖和连接设备见 [README](../README.md#安装与连接)。以下命令均在仓库根目录执行；将示例视频路径替换为自己的本地文件。

## 命令与参数

```sh
uv run streamdock --help
uv run streamdock play --help
uv run streamdock info
uv run streamdock devices
```

`info` 输出内置设备参考资料和按键布局，不探测硬件；`devices` 枚举已连接设备。

```sh
# 完整播放；Ctrl+C 停止
uv run streamdock play "/path/to/video.mp4"

# 从第 30 秒开始，以 8 fps 播放 20 秒
uv run streamdock play "/path/to/video.mp4" --start 30 --seconds 20 --fps 8

# 循环所选片段
uv run streamdock play "/path/to/video.mp4" --start 30 --seconds 20 --loop

# 从 devices 输出中复制目标设备的 serial
uv run streamdock play "/path/to/video.mp4" --serial "YOUR_DEVICE_SERIAL"
```

| 参数 | 默认值 | 用途与范围 |
| --- | --- | --- |
| `VIDEO` | 必填 | 本地视频路径，例如 MP4、MOV、MKV、WebM；以本机 FFmpeg 的解码能力为准 |
| `--start SECONDS` | `0` | 非负起始秒数；设备播放时须小于视频时长 |
| `--seconds SECONDS` | 播放至结束 | 大于 0 的片段长度 |
| `--fps FPS` | `10` | 输出帧率，整数 `1..30` |
| `--loop` | 关闭 | 重复整个视频或所选片段，循环期间保持设备连接 |
| `--key KEY` | 全部 15 键 | 仅在指定逻辑按键播放，整数 `1..15` |
| `--gap PIXELS` | `0` | 水平、垂直按键间距，非负整数；单键播放忽略 |
| `--quality QUALITY` | `75` | 设备 JPEG 质量，整数 `1..95`；不影响预览 |
| `--preview OUTPUT.mp4` | 关闭 | 导出离线预览，不连接设备 |
| `--serial SERIAL` | 自动选择唯一 M18 | 选择设备序列号 |
| `--no-cache` | 关闭 | 实时解码与编码，绕过已有缓存 |
| `--rebuild-cache` | 关闭 | 强制重建当前视频及参数对应的缓存 |

`--loop` 和 `--rebuild-cache` 均不能与 `--preview` 同用；`--no-cache` 与 `--rebuild-cache` 互斥。

## 按键与跳转

`--key` 使用从上到下、从左到右的逻辑编号：

```text
 1  2  3  4  5
 6  7  8  9 10
11 12 13 14 15
```

底部三个无屏按键的操作见 [README 播放控制](../README.md#播放控制)。快进至末尾时停在最后一个采样区间；暂停跳转会显示目标位置的一帧，随后保持暂停。使用缓存时，片段起点和跳转位置按输出帧率对齐。

播放过程中检测到睡眠唤醒、USB 断开或通信失败时，会释放旧连接，每秒尝试重连原设备。重连后从中断位置继续，保持暂停状态和片段范围；暂停时也会检查连接。睡眠或重连等待时间不计入视频进度，Ctrl+C 可退出等待。首次启动时找不到设备仍会直接报错。

系统睡眠期间不能继续向设备发送视频。恢复功能需要播放进程仍在运行；退出程序或重启电脑后需重新执行播放命令。运行中断超过两秒也会触发重新连接，以免继续使用可能失效的 USB 连接。

## 间距补偿与预览

`--gap` 用于补偿相邻可见屏幕之间的实体边框。视频先等比缩放、补黑边至 `(320 + 4×gap) × (192 + 2×gap)` 的虚拟画布，再裁出各键的 64×64 显示区域；被边框遮挡的内容不发送。

间距以单键可见区域的 64 像素为基准，可用下式估算：

```text
gap ≈ 64 × 实际间隔宽度 / 单键可见显示宽度
```

水平与垂直间距使用同一个值。尚无本机实测尺寸，下面的 `8` 仅为示例，对应 352×208 画布。可先导出预览再调整：

```sh
uv run streamdock play "/path/to/video.mp4" --gap 8 --seconds 5 --preview previews/gap.mp4
open previews/gap.mp4
```

预览使用相同的缩放和取帧参数，输出无音频 MP4。`--gap 0` 时用网格线标出按键边界，有间距时用黑色条带表示被遮挡区域；单键预览不绘制网格。预览不使用设备 JPEG 缓存，也不模拟 JPEG 压缩或 USB 速度。

输出目录会自动创建；已有输出文件不会被覆盖，需改用新的文件名或自行移走旧文件。

## 视频缓存

设备播放默认先将整段视频转换为 JPEG 缓存，保存在仓库根目录的 `.cache/videos/`。首次转换在连接设备前完成，终端显示进度；之后播放、循环和跳转直接读取缓存，无需重复解码和编码。生成与播放均逐帧处理，不会将整段视频装入内存。

```sh
# 自动生成或复用缓存
uv run streamdock play "/path/to/video.mp4" --gap 32 --loop

# 绕过缓存，实时解码与编码；保留已有缓存
uv run streamdock play "/path/to/video.mp4" --gap 32 --no-cache

# 强制重建当前视频和参数对应的缓存
uv run streamdock play "/path/to/video.mp4" --gap 32 --rebuild-cache
```

源文件路径、大小、修改时间、帧率、JPEG 质量、间距或 `--key` 选择发生变化时会生成新缓存。`--start`、`--seconds` 和 `--loop` 复用整段视频的同一份缓存；单键模式下更改 `--gap` 不会重建。格式版本等内部失效规则见[缓存实现](development.md#缓存实现)。

重建中断会保留原有完整缓存，结构不完整的缓存会自动重建。播放中发现帧损坏时会停止并提示使用 `--rebuild-cache`。

缓存不自动清理，不同视频和参数的缓存会累计占用磁盘空间。停止播放后可删除 `.cache/videos/` 释放空间；官方 SDK 随应用安装，不属于缓存。

## 常见问题

| 现象 | 检查与处理 |
| --- | --- |
| 找不到视频文件 | 确认 `VIDEO` 是存在的本地文件，路径含空格时加引号 |
| 找不到 `ffmpeg` 或 `ffprobe` | 安装完整 FFmpeg，并确认两条命令都在 `PATH` 中 |
| SDK / 原生通信库加载失败 | 重新安装对应系统的构建包；源码运行时执行 `python3 scripts/update_sdk.py --verify` 校验文件，核对当前系统和架构是否受支持 |
| `devices` 输出 `[]` | 检查 USB 连接；SDK 尚未枚举到设备 |
| 多台 M18 或未发现匹配设备 | 检查 `devices` 输出，使用正确的 `--serial` |
| 无法打开设备 | 退出可能占用设备的 Mirabox StreamDock 软件后重试 |
| 首次播放等待较久 | 等待整段视频转换完成，或用 `--no-cache` 实时播放 |
| 缓存帧校验失败 | 使用相同视频和播放参数，加上 `--rebuild-cache` 重建 |
| 预览已存在 | 更换输出文件名，或自行移走旧文件 |
