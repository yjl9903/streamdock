# 脚本 API 与运行时

## CLI 与脚本加载

以下命令在仓库根目录执行，`dashboard.py` 使用 README 中的计数器脚本。

```sh
uv run decklet info
uv run decklet devices
uv run decklet run --help
uv run decklet run ./dashboard.py
uv run decklet run --serial YOUR_DEVICE_SERIAL ./dashboard.py
```

`info` 输出参考设备资料，不探测硬件。`devices` 枚举设备；运行时目前只接入 M18。`run` 加载一个导出 `app = App()` 的 `.py` 文件，一个进程控制一台设备。`--serial` 必须放在脚本路径前，脚本参数放在 `--` 后。

脚本只导入一次；同目录模块可在顶层或回调内导入。每个应用拥有独立包名，推荐使用 `from .helper import ...` 相对导入，也支持 `import helper`。工作目录不会改变。资源文件建议使用 `ctx.script_dir / "assets/icon.png"`；`ctx.args` 为脚本参数列表，加载时 `sys.argv` 同样设为脚本路径与参数。因此可以在顶层用 `argparse` 解析，让 `--help` 在连接设备前退出。Python 依赖使用当前环境，CLI 不自动安装依赖。脚本按普通 Python 程序执行。

例如，视频应用用 `argparse` 解析 `--` 后的参数：

```sh
uv run decklet run apps/video/app.py -- --help
```

## App 与事件

```python
from decklet import App, Context, KeyEvent

app = App()


@app.on_key(1, action="press")
async def press(ctx: Context, event: KeyEvent):
    print(event.key, event.action, event.timestamp)


@app.on_key(action="release")
async def release(ctx: Context, event: KeyEvent):
    print("任意按键松开", event.key)


@app.every(1.0)
async def tick(ctx: Context):
    print("每秒更新一次")
```

所有处理函数必须是 `async def`。同一 App 的生命周期、按键和定时处理函数串行执行，同一个按键持续按住只产生一次 `press`，松开产生 `release`。`timestamp` 是单调时钟秒数；事件中不包含 SDK 对象。输入队列有上限，处理函数长期阻塞导致队列溢出时明确报错退出，不静默丢失按下/松开状态。

`every(seconds)` 的间隔必须为正有限数，首次在初始化完成后的一个间隔触发。同一个定时任务最多保留一次待执行通知，错过的周期不会集中补执行。定时任务在断线期间继续运行。

M18 的屏幕键为 1–15，底部无屏键为 16–18：

```text
 1  2  3  4  5
 6  7  8  9 10
11 12 13 14 15
   16  17  18
```

底部物理位置仍需实机核对。`ctx.device` 在生命周期回调中提供 `model`、`serial`、`rows`、`columns`、`key_image_size`、`screen_keys` 和 `input_keys`，`ctx.device.profile.canvas_size(gap)` 返回完整画布尺寸。

## 画面与刷新

```python
from PIL import Image

# 尺寸必须匹配设备；M18 为 64×64
ctx.display.set_key(1, Image.new("RGB", ctx.device.key_image_size, "red"))

# M18 默认 320×192；gap=8 时为 352×208
size = ctx.device.profile.canvas_size(gap=8)
ctx.display.set_canvas(Image.new("RGB", size, "navy"), gap=8)

ctx.display.clear(1)  # 将一个键设为黑色
ctx.display.clear()  # 将所有屏幕键设为黑色

# 可选：等待此前的更新（或覆盖它的更新）提交到 USB
await ctx.display.flush()
```

这些方法使用逻辑按键编号。尺寸错误或给无屏键绘图会报错，不做隐式缩放。设置图片时获取 RGB 快照，随后修改原图不会改变待发送内容。`set_canvas` 按布局切片，跳过按键之间的 `gap` 区域。

更新先合并到每个键的最新目标画面，独立 USB 线程编码并批量发送。连续设置多键会合并；发送期间的新更新保留至下一批。USB 速度不足时不会积累历史帧。相同 JPEG 内容省略实际写入。默认 JPEG 质量为 75。

`flush()` 可在事件或后台协程中使用，断线时等待重连；退出时未完成的等待会失败。它表示运行时已向底层提交，不能证明设备物理显示完成，也不保证多键同时更新。需要提交最后一帧时，先 `await ctx.display.flush()` 再 `ctx.stop()`。

已有编码缓存的应用可使用 `ctx.display.set_jpegs([(logical_key, jpeg_bytes), ...])`，避免重复编码。`decklet.rendering.encode_key()` 和 `encode_canvas()` 提供相同尺寸、质量与间距规则的独立编码函数，输出仍是逻辑编号。

## 生命周期、重连与退出

| 装饰器 | 调用约定 |
| --- | --- |
| `@app.on_start` | 第一次连接成功后执行一次；重连不重新导入脚本或重复初始化 |
| `@app.on_connect` | 初始化完成后和每次重连后执行；已失效的连接通知跳过 |
| `@app.on_disconnect` | 检测到连接丢失后执行 |
| `@app.on_stop` | 初始化开始过的应用退出时执行，包括初始化失败；每个清理函数都有执行机会 |

`ctx.connected` 表示当前真实连接状态。生命周期通知与其他处理函数排队执行，因此处理较慢时，收到断线通知的瞬间设备可能已经重连。USB 线程独立维持连接，不等待用户回调结束。

首次找不到匹配设备直接报错；首次连接成功后锁定该序列号，每秒尝试重连原设备。断线清除按键去重状态和旧连接输入，保留应用状态、周期任务与最新画面，重连完整重绘应用设置过的键。未由应用设置的键不会被主动清空。运行中断或睡眠唤醒后也会重新打开连接。

```python
@app.on_stop
async def stop(ctx: Context):
    # 关闭自己创建的网络连接等；设备已由运行时释放
    pass
```

`ctx.stop()`、Ctrl+C 或 SIGTERM 启动退出。运行时停止分发，取消受管后台任务，等待正在进行的设备操作结束并关闭 USB，然后执行 `on_stop`。`on_stop` 用于资源清理，不再发送画面或创建任务。多个清理错误与原始应用错误会一起报告。

## 后台任务与独立 Python 集成

```python
import asyncio


@app.on_start
async def start(ctx: Context):
    async def worker():
        while True:
            await asyncio.sleep(5)
            # 异步获取数据，再在此更新画面

    ctx.create_task(worker(), name="data-refresh")
```

`ctx.create_task()` 管理的任务在退出时取消并等待；未处理异常会终止应用并显示 traceback。任务在应用事件循环中运行，可直接调用画面接口；它与事件处理函数之间仍可能在 `await` 处交错，需要自行协调共享状态。

网络请求使用异步 API。同步 I/O 或耗时计算放到 `asyncio.to_thread()` 或自己的工作线程；不要在工作线程直接调用 `ctx`、`Display` 或 `asyncio.Queue`。取消协程不会强制终止线程，长任务应像视频缓存示例一样实现协作取消并等待资源清理。

已有 Python 程序可以直接使用公开入口，无需 CLI：

```python
import asyncio
from decklet import App, run_app

app = App()
# 注册回调……
asyncio.run(run_app(app, serial="YOUR_DEVICE_SERIAL"))
```

底层设备枚举与连接适配保留在 `decklet.hardware`，应用通常使用上述公共接口即可。当前不包含热重载、多设备运行和 UI 组件系统。
