# 视频播放器开发指南

## 代码结构

| 文件 | 职责 |
| --- | --- |
| [app.py](app.py) | 脚本入口，导出 `App` |
| [cli.py](cli.py) | 参数解析、生命周期注册及画面提交 |
| [controls.py](controls.py) | 将 `KeyEvent` 转换为播放操作 |
| [player.py](player.py) | 异步播放、暂停、跳转和时钟 |
| [playback.py](playback.py) | FFmpeg 解码、编码辅助及离线预览 |
| [cache.py](cache.py) | 视频 JPEG 缓存 |
| [tests/](tests/) | 单元测试、应用集成测试及模拟设备 |

## 应用运行流程

入口是 `app.py`，它解析脚本参数并导出 `App`。`--help` 和 `--preview` 在加载阶段结束，不连接 USB。正式播放在 `on_start` 中读取媒体信息和准备缓存；`on_connect` 启动由 `ctx.create_task()` 管理的播放协程。

`cli.py` 的 `DisplayOutput` 只调用 `ctx.display.set_jpegs()` 与 `await ctx.display.flush()`。帧缓存使用逻辑按键编号，硬件槽位映射完全由库处理。`controls.py` 消费标准 `KeyEvent`，`player.py` 管理暂停、跳转和时钟，阻塞的解码及 SQLite 读取在独立工作线程执行。

断线时取消播放协程并关闭解码器，保留播放器的进度和暂停状态；重连后由 `on_connect` 重新启动。连接重试、序列号锁定与按键去重由框架负责。输出统计中的 `sent_frames` 表示提交并等待刷新完成的帧数，相同图片可能由框架省略实际 USB 写入。

## 按键与设备输出

框架负责按键边沿去重；视频示例由 [controls.py](controls.py) 绑定底部无屏按键。

| 位置 | SDK 逻辑编号 | 硬件码 | 播放命令 |
| --- | --- | --- | --- |
| 左 | 16 | `0x25` | `rewind` |
| 中 | 17 | `0x30` | `pause` |
| 右 | 18 | `0x31` | `forward` |

逻辑编号与硬件码来自[官方 M18 驱动](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDockM18.py)；物理位置顺序沿用当前项目绑定，仍需实机核对。

固定版本 SDK 的背景 MP4 接口仅支持 N4Pro、XL、M3，M18 不在其中，所以本项目使用按键图片流。参见[官方视频接口说明](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/README.md)。

## 缓存实现

使用方式和清理方法见[视频缓存](README.md#视频缓存)。实现位于 [cache.py](cache.py)，每份缓存为一个 SQLite 文件：

- `metadata` 表存储缓存身份和总帧数；`frames` 表以 `idx` 为主键，存储 JPEG 数据及 CRC32 校验值。
- 每帧按逻辑按键顺序存储各张 JPEG，前置四字节大端长度；读取时校验帧连续性、CRC32、长度及 JPEG 首尾标记。
- 文件名由缓存身份的 SHA-256 得到。身份包含源文件绝对路径、大小、纳秒修改时间、渲染参数、逻辑按键与图片尺寸、Pillow 版本和 `CACHE_VERSION`。
- 构造缓存身份时将 `start` 归零、`seconds` 清空；单键模式将 `gap` 归零。`loop` 不参与身份计算。
- 生成时逐帧解码、编码和写入临时数据库，完成后再次核对源文件身份，再用 `os.replace` 原子替换正式文件；中断重建保留旧缓存。
- 加载时检查元数据、帧数与索引范围，结构不完整则重建；帧内容在播放读取时校验，失败则提示 `--rebuild-cache`。

当前 `CACHE_VERSION = 2`。修改编码格式或渲染语义时应递增 `CACHE_VERSION`，避免复用不兼容缓存。

## 测试

在仓库根目录运行：

```sh
uv run python -m unittest discover -s apps/video/tests -t . -v
```

测试使用模拟设备，无需连接 USB。FFmpeg 集成测试会生成临时视频，需要本机提供 `ffmpeg`、`ffprobe` 和 `libx264` 编码器，安装方式见[视频依赖](README.md#安装视频依赖)。没有 `ffmpeg` 时，相关测试会跳过。

| 测试文件 | 覆盖内容 |
| --- | --- |
| [test_app.py](tests/test_app.py) | 脚本加载、离线 CLI、完整应用运行和重连 |
| [test_cache.py](tests/test_cache.py) | 缓存生成、复用、校验及损坏处理 |
| [test_controls.py](tests/test_controls.py) | 按键映射、暂停、跳转、循环及重连状态恢复 |
| [test_decoder.py](tests/test_decoder.py) | FFmpeg 解码、重采样、补黑边及资源清理 |
| [test_gap.py](tests/test_gap.py) | 间距补偿及预览 |
| [test_playback.py](tests/test_playback.py) | 画布切片、逻辑键编号、帧调度及管道读取 |

实机画面、底部按键位置和实际间距仍需连接设备确认，自动化测试不能替代这些检查。
