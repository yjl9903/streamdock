# 视频播放器

将本地视频拼接播放到 M18 的 15 个按键屏，也可单键播放或导出离线预览。支持片段、循环、暂停和跳转，所有播放均无音频。

## 运行

在仓库根目录执行，将视频路径替换为自己的文件：

```sh
# 完整播放；Ctrl+C 停止
uv run decklet run apps/video/app.py -- "/path/to/video.mp4"

# 从第 30 秒开始，循环播放 20 秒片段
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --start 30 --seconds 20 --loop

# 无需设备：导出 5 秒预览
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --seconds 5 --preview previews/video.mp4
```

预览完成后输出 `预览已保存：<绝对路径>`；设备播放正常结束后输出 JSON 统计，包含 `sent_frames`、`dropped_frames` 和 `loops`。首次设备播放会先缓存整段视频，想立即实时解码可加 `--no-cache`。

## 安装视频依赖

需要包含 `ffmpeg`、`ffprobe` 的 [FFmpeg](https://ffmpeg.org/)；导出预览还需要 `libx264` 编码器。macOS 使用 Homebrew 安装：

```sh
brew install ffmpeg
```

## 按键与跳转

| 底部无屏键 | 操作 |
| --- | --- |
| 16（左） | 快退 10 秒 |
| 17（中） | 暂停 / 继续 |
| 18（右） | 快进 10 秒 |

物理位置仍需实机核对。暂停时也能跳转，显示目标位置的一帧后保持暂停。跳转限于当前视频或指定片段，快进至末尾会停在最后一个采样区间；缓存播放时按输出帧率对齐。

断线或睡眠唤醒后，每秒尝试重连原设备，恢复播放位置和暂停状态；等待时间不计入视频进度。首次启动找不到设备会报错，退出进程后需重新执行命令。Ctrl+C 也可退出重连等待。

## 命令参数

```sh
uv run decklet run apps/video/app.py -- --help

# 多台设备时，--serial 放在脚本路径前
uv run decklet run --serial "YOUR_DEVICE_SERIAL" apps/video/app.py -- "/path/to/video.mp4"
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
| `run --serial SERIAL` | 自动选择唯一 M18 | 框架参数，必须放在脚本路径前 |
| `--no-cache` | 关闭 | 实时解码与编码，绕过已有缓存 |
| `--rebuild-cache` | 关闭 | 强制重建当前视频及参数对应的缓存 |

`--loop` 和 `--rebuild-cache` 均不能与 `--preview` 同用；`--no-cache` 与 `--rebuild-cache` 互斥。

`--key` 使用从上到下、从左到右的屏幕键编号：

```text
 1  2  3  4  5
 6  7  8  9 10
11 12 13 14 15
```

## 间距补偿与预览

`--gap` 用于补偿相邻可见屏幕之间的实体边框。视频先等比缩放、补黑边至 `(320 + 4×gap) × (192 + 2×gap)` 的虚拟画布，再裁出各键的 64×64 显示区域；被边框遮挡的内容不发送。

间距以单键可见区域的 64 像素为基准，可用下式估算：

```text
gap ≈ 64 × 实际间隔宽度 / 单键可见显示宽度
```

水平与垂直间距使用同一个值。尚无本机实测尺寸，下面的 `8` 仅为示例，对应 352×208 画布。可先导出预览再调整：

```sh
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --gap 8 --seconds 5 --preview previews/gap.mp4
open previews/gap.mp4
```

预览使用相同的缩放和取帧参数，输出无音频 MP4。`--gap 0` 时用网格线标出按键边界，有间距时用黑色条带表示被遮挡区域；单键预览不绘制网格。预览不使用设备 JPEG 缓存，也不模拟 JPEG 压缩或 USB 速度。

输出目录会自动创建；已有输出文件不会被覆盖，需改用新的文件名或自行移走旧文件。

## 视频缓存

设备播放默认先将整段视频转换为 JPEG 缓存，保存在当前工作目录的 `.cache/videos/`。转换时终端显示进度，后续播放、循环和跳转直接复用缓存。生成与播放均逐帧处理，不会将整段视频装入内存。

```sh
# 自动生成或复用缓存
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --gap 32 --loop

# 绕过缓存，实时解码与编码；保留已有缓存
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --gap 32 --no-cache

# 强制重建当前视频和参数对应的缓存
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --gap 32 --rebuild-cache
```

源文件路径、大小、修改时间、帧率、JPEG 质量、间距或 `--key` 选择发生变化时会生成新缓存。`--start`、`--seconds` 和 `--loop` 复用整段视频的同一份缓存；单键模式下更改 `--gap` 不会重建。

重建中断会保留原有完整缓存，结构不完整的缓存会自动重建。播放中发现帧损坏时会停止并提示使用 `--rebuild-cache`。

缓存不自动清理，不同视频和参数的缓存会累计占用磁盘空间。停止播放后可删除 `.cache/videos/` 释放空间。

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
