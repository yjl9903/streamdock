# Decklet

Decklet 是用 Python 脚本编写按键屏应用的框架，当前支持 StreamDock 设备：库提供设备连接、按键事件、图片渲染和断线重连，CLI 加载用户导出的 `App`，脚本负责画面与交互。

当前适配目标是 macOS 上的 Mirabox **M18V25E**：15 个 64×64 按键屏和 3 个底部无屏按键。设备画面与物理按键位置仍需实机验证，详见[硬件验证范围](docs/development.md#硬件验证范围)。

## 安装与连接

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。在仓库根目录执行：

```sh
uv sync --locked
uv run decklet devices
```

SDK 和原生通信库随项目提供。连接 USB 后，退出可能占用设备的 Mirabox StreamDock 软件。`devices` 输出 JSON 数组，`[]` 表示未发现设备；当前 `runtime_supported: true` 表示运行时支持的 M18。

## 运行自己的脚本

```python
# dashboard.py
from PIL import Image, ImageDraw
from decklet import App, Context, KeyEvent

app = App()
count = 0


def render(ctx: Context):
    image = Image.new("RGB", ctx.device.key_image_size, "#18212b")
    ImageDraw.Draw(image).text((12, 24), str(count), fill="white")
    ctx.display.set_key(1, image)


@app.on_start
async def start(ctx: Context):
    render(ctx)


@app.on_key(1)
async def increment(ctx: Context, event: KeyEvent):
    global count
    count += 1
    render(ctx)
```

```sh
uv run decklet run ./dashboard.py

# 多台设备时选择一台；-- 后的参数交给脚本
uv run decklet run --serial YOUR_DEVICE_SERIAL ./dashboard.py -- --city Shanghai

# 仓库自带的计数器：按键 1 计数，底部按键 18 退出
uv run decklet run apps/counter/app.py
```

按键编号从 1 开始，按上到下、左到右排列。脚本使用 Pillow 图片和逻辑编号，无需处理 JPEG 编码或硬件槽位。Ctrl+C 退出并清理设备连接；脚本异常会显示 traceback。画面更新会覆盖对应按键，退出不会恢复原图标。

## 视频示例

[视频应用](apps/video/README.md) 展示整屏渲染、异步任务、按键交互和重连后的状态恢复。它保留了缓存、片段、循环、暂停、跳转、间距补偿及离线预览，需要额外安装包含 `ffmpeg`、`ffprobe` 的 [FFmpeg](https://ffmpeg.org/)。

```sh
brew install ffmpeg

# 播放本地视频（无音频）
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --loop

# 无需设备：导出 5 秒预览
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --seconds 5 --preview previews/video.mp4
```

视频已从库内命令移到 `apps/`，原 `streamdock play` 入口不再提供。示例随源码包提供，wheel 仅安装框架。

## 文档

- [脚本 API 与生命周期](docs/usage.md)：事件、定时任务、画面、脚本参数和重连约定。
- [视频示例指南](apps/video/README.md)：视频参数、缓存、跳转与预览。
- [开发指南](docs/development.md)：测试、代码结构、打包和 SDK 同步。
