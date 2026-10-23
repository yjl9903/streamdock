# Decklet

用 Python 为 StreamDock 编写按键屏应用：用 Pillow 绘图、响应按键、定时更新，设备连接与断线重连交给 Decklet。

当前适配目标是 macOS 上的 Mirabox **M18V25E**：15 个 64×64 按键屏和 3 个底部无屏按键。设备画面与物理按键位置仍需实机验证，详见[硬件验证范围](docs/development.md#硬件验证范围)。

## 示例应用

以下示例均在完成[安装与连接](#安装与连接)后，于仓库根目录运行。

### 计数器

在屏幕键 1 显示计数，每按一次加一，按底部无屏键 18 退出。

```sh
uv run decklet run apps/counter/app.py
```

使用说明见[计数器文档](apps/counter/README.md)。

### 视频播放器

将本地视频拼接播放到多个按键屏，底部按键控制暂停和跳转，断线重连后恢复播放进度。播放无音频，需要额外[安装 FFmpeg](apps/video/README.md#安装视频依赖)。

```sh
uv run decklet run apps/video/app.py -- "/path/to/video.mp4" --loop
```

将视频路径替换为自己的文件。缓存、片段播放和参数见[视频播放器文档](apps/video/README.md)，也可先生成无需设备的[离线预览](apps/video/README.md#间距补偿与预览)。

## 安装与连接

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。先获取仓库并安装依赖：

```sh
git clone https://github.com/yjl9903/decklet.git
cd decklet
uv sync --locked
```

SDK 和原生通信库随项目提供，无需另行下载。通过 USB 连接设备，退出可能占用设备的 Mirabox StreamDock 软件，再检查连接：

```sh
uv run decklet devices
```

命令输出 JSON 数组；`[]` 表示未发现设备，设备条目的 `runtime_supported: true` 表示框架支持该设备。多台 M18 同时连接时，从输出中复制 `serial`，将 `--serial` 放在脚本路径前：

```sh
uv run decklet run --serial YOUR_DEVICE_SERIAL apps/counter/app.py
```

## 运行自己的脚本

每个应用是一个导出 `app = App()` 的 Python 脚本，事件处理函数使用 `async def`。下面的脚本启动时显示 `0`，每按一次屏幕键 1 加一。保存为 `dashboard.py`：

```python
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
```

屏幕键从 1 开始，按上到下、左到右编号。按 Ctrl+C 退出并释放连接。

## 脚本 API

| 你想做什么 | 接口与说明 |
| --- | --- |
| 响应按下、松开或定时更新 | [`@app.on_key()`、`@app.every()`](docs/usage.md#app-与事件) |
| 更新单键或整块画布 | [`ctx.display.set_key()`、`set_canvas()`](docs/usage.md#画面与刷新) |
| 初始化、处理断线或清理资源 | [生命周期回调](docs/usage.md#生命周期重连与退出) |
| 读取脚本参数和资源文件 | [`ctx.args`、`ctx.script_dir`](docs/usage.md#cli-与脚本加载) |
| 运行异步后台任务或嵌入已有程序 | [`ctx.create_task()`、`run_app()`](docs/usage.md#后台任务与独立-python-集成) |

完整约定见[脚本 API 与运行时](docs/usage.md)。

## 使用前须知

- 一个进程控制一台设备；当前不提供热重载或 UI 组件系统。
- 画面更新会覆盖对应按键，退出不会恢复原图标。
- 首次启动找不到设备会报错；运行中断线后自动重连原设备，保留应用状态并重绘已设置的画面。
- 处理函数中应避免阻塞操作，耗时任务的写法见[后台任务](docs/usage.md#后台任务与独立-python-集成)。脚本异常会显示 traceback。

## 许可证

Decklet 使用 [MIT License](LICENSE)。

内置 Mirabox SDK 保留其独立的 [MIT License](src/streamdock/_vendor/mirabox/LICENSE) 和版权声明。
