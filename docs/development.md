# 开发指南

[返回 README](../README.md) · [使用指南](usage.md)

## 开发与验证

环境要求和安装方式见 [README](../README.md#安装与连接)。在仓库根目录同步依赖并运行测试：

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s . -v
```

测试使用 `unittest`。根目录 `tests/` 存放框架测试，应用自己的测试随应用放在 `apps/<name>/tests/`；上述命令从仓库根目录发现并运行两部分。硬件相关测试通过模拟对象验证发送和清理行为，无需连接设备；FFmpeg 集成测试生成临时视频，没有 `ffmpeg` 时会跳过，执行这些测试还需要 `libx264` 编码器。

自有 Python 代码使用 Ruff 检查和格式化；可运行 `uv run ruff check --fix .` 与 `uv run ruff format .` 整理代码。`_vendor` 中的 SDK 保留同步结果，不参与格式化。Ruff 版本由开发依赖和 `uv.lock` 固定，CI 执行相同检查。

| 测试范围 | 覆盖内容 |
| --- | --- |
| `tests/test_runtime.py` | 生命周期、输入去重、USB 单线程、更新合并、原设备重连、错误与取消清理 |
| `tests/test_display.py` | 图片快照、逻辑编号、间距、并发更新确认与刷新等待 |
| `apps/counter/tests/` 和 `apps/video/tests/test_app.py` | 真实 FFmpeg 与模拟设备驱动的视频应用、离线 CLI 和计数器 |
| `tests/test_loader.py` | 脚本参数、同目录导入、路径恢复和加载错误 |
| `tests/test_hardware.py` | SDK 加载、通信错误和设备资源清理 |
| `tests/test_update_sdk.py` | SDK 同步、校验、补丁及回滚 |
| `apps/video/tests/` | 视频缓存、解码、预览、间距、暂停、跳转与恢复 |

## GitHub CI

GitHub Actions 的 `CI` 工作流在推送到 `main`、提交或更新 PR，以及手动触发时运行。配置位于 `.github/workflows/ci.yml`。

默认只运行 Ubuntu / Python 3.11。需要检查其他组合时，在 Actions 中手动运行工作流并勾选 `full_matrix`，即可运行完整的 macOS、Ubuntu × Python 3.11、3.14 测试矩阵。每组执行：

1. 安装 FFmpeg，并确认 `ffmpeg`、`ffprobe` 和 `libx264` 可用，避免集成测试因缺少 FFmpeg 被跳过。
2. 用 `uv sync --locked` 安装锁定依赖，离线校验 SDK 文件与补丁哈希，验证原生库可加载，再运行全部 `unittest` 测试。Ubuntu / Python 3.11 另外从上游下载固定版本，检查同步结果完全一致。
3. 用 `uv build --no-sources` 构建源码包和 wheel，检查源码包中的 README、`docs/` 和 `apps/` 与工作区一致，并核对 wheel 的平台标签、许可证、来源记录及 SDK 文件哈希。
4. 将 wheel 安装到独立虚拟环境，在仓库目录之外运行 `decklet --help`、`run --help` 和 `info`，加载内置 SDK，并运行复制到临时目录的视频示例 `--help`，验证安装包与脚本的同目录导入不依赖源码目录。

工作流固定 Action 提交及 uv 版本，并缓存 uv 下载内容；配置方式参考 [uv 的 GitHub Actions 集成指南](https://docs.astral.sh/uv/guides/integration/github/)。新提交会取消同一分支尚未完成的运行。CI 加载固定版本 SDK，但不枚举或连接 USB 设备，不验证实机播放，也不发布构建产物。

## 官方 SDK 版本管理

SDK 的精简运行副本位于 `src/streamdock/_vendor/mirabox/`，随源码包和 wheel 提供。普通用户只需 `uv sync --locked`，无需初始化子模块、克隆 SDK 或设置环境变量。当前上游基线为 `7f0d47fe91033b0883edf29b574a6c74ea9bed00`，精确来源以 [SOURCE.json](../src/streamdock/_vendor/mirabox/SOURCE.json) 为准。

上游直接构建的 wheel 缺少原生通信库，因此保留上游运行模块及配套原生库，保留既有的 `streamdock._vendor.mirabox` 私有命名空间和导入补丁。Decklet 的硬件适配层引用该路径；项目重命名不修改 vendor 内容或来源记录。业务适配继续放在 `hardware.py`，不直接修改 SDK 副本。

### 同步到新的上游版本

先审查上游差异，选择完整的 40 位 commit，再执行：

```sh
uv run python scripts/update_sdk.py --revision <已审查的完整commit>
uv run python scripts/update_sdk.py --verify
uv run python -m unittest discover -s . -v
uv build --no-sources
uv run python scripts/check_wheel.py dist/<本次生成的平台wheel文件名>
```

脚本只使用 Python 标准库和 Git，也可直接用 `python3 scripts/update_sdk.py`。修改补丁或配置后，旧 SDK 的构建校验会暂时失败，此时应使用 `python3` 执行同步，不要通过会先构建项目的 `uv run`。安装和构建过程不会下载 SDK。

同步脚本会下载指定 commit 的归档，在临时目录按文件清单复制运行模块、通信库和许可证，检查并应用补丁、编译检查 Python 源码，再生成来源记录。全部检查通过才替换旧目录。补丁冲突、文件丢失或发现未处理的公开包导入会中止；当前 SDK 保持原样。若 SDK 副本存在手工修改，脚本会拒绝覆盖。

升级后审查 `src/streamdock/_vendor/mirabox/`、`scripts/sdk/` 的 diff，特别是原生库变动；验证实机播放、按键、断线重连后，将这些文件与适配修改一起提交，并更新本文基线及下方的官方源码链接。脚本不会提交代码。

### 复现和离线校验

```sh
# 不联网：核对所有收录文件、清单和补丁的 SHA-256
python3 scripts/update_sdk.py --verify

# 从上游重新生成记录的版本，与当前副本逐文件比较，不改写 SDK
python3 scripts/update_sdk.py --check

# 已有上游 Git 仓库时，直接读取指定 commit 的 Git 对象，忽略工作区修改
python3 scripts/update_sdk.py --check --source /absolute/path/to/upstream-sdk
```

`--check` 默认读取 `SOURCE.json` 的 commit；更新必须显式传入 `--revision`，不接受分支或可移动的 tag。同一 commit、文件清单和补丁会生成相同的文件和来源记录，不记录时间戳或机器路径。

### 文件清单与补丁

- [config.json](../scripts/sdk/config.json) 列出收录文件、许可证、补丁顺序以及各平台的库名与 wheel 标签。保留 Python 运行模块，因为设备管理器会加载多个型号；排除示例、媒体、上游测试及未支持平台的库。
- [0001-private-imports.patch](../scripts/sdk/patches/0001-private-imports.patch) 只改绝对导入路径，不修改设备协议。补丁不再适用时，在目标 commit 的临时副本上重新制作 unified diff，审查后更新补丁再同步。
- `SOURCE.json` 记录仓库地址、commit、每个上游原文件的 SHA-256、补丁与配置 SHA-256、应用补丁后的文件 SHA-256。

上游新增或删除运行文件时，维护者需要审查并更新文件清单。删除仍在清单中的文件会报错；从清单移除后，同步会将它从新副本中删除。不要通过手改 `SOURCE.json` 来绕过校验。

### 分发与平台范围

源码包包含全部已收录平台库、同步脚本、补丁和来源记录。wheel 只包含构建平台所需的通信库，并使用平台标签：macOS 11+ universal2（Intel / Apple Silicon）、Linux x86_64 或 aarch64。Windows 和其他架构当前没有构建配置。Linux wheel 使用 `linux_*` 标签，不宣称 manylinux/musllinux 兼容；实际运行还受上游二进制和系统库限制。M18 实机适配目标仍为 macOS，Linux CI 只验证加载与非硬件逻辑。

[hatch_build.py](../hatch_build.py) 在构建前校验 SDK 完整性，[check_wheel.py](../scripts/check_wheel.py) 检查最终 wheel 的文件与平台元数据。升级原生库时需要重新检查架构、最低系统版本和动态链接依赖，必要时调整 `config.json` 的平台标签；固定 commit 不代表二进制兼容性自动成立。

旧 `.cache/StreamDock-Device-SDK/` 不再使用；确认没有个人改动后可自行删除。`STREAMDOCK_SDK_PATH` 不再读取，SDK 不依赖外部路径。

## 代码结构

```text
src/decklet/
  __init__.py            App、Context、Display、设备信息与 run_app 公共入口
  app.py                 生命周期、按键、定时任务注册及应用 Context
  events.py              不依赖 SDK 的 KeyEvent
  display.py             每个逻辑键的最新目标画面、快照与刷新等待
  rendering.py           画布切片和 JPEG 编码，始终使用逻辑编号
  runtime.py             事件分发、设备工作线程、断线重连和退出清理
  loader.py              脚本加载、参数与同目录导入
  cli.py                 info / devices / run 注册和错误报告
  commands/run.py        脚本运行入口及 SIGTERM 处理
  device.py              设备布局、能力和底层图片槽位配置
  hardware.py            SDK 适配、连接探测和传输
src/streamdock/_vendor/
  mirabox/               保持原样的固定版本 SDK 和原生库
apps/
  counter/
    app.py               最小交互应用
    tests/               计数器应用测试
  video/
    app.py               视频应用入口，导出 app
    cli.py               示例参数及 App 生命周期注册
    controls.py          KeyEvent 到视频操作的映射
    player.py            异步播放、暂停、跳转和时钟
    playback.py          FFmpeg 解码、编码辅助及离线预览
    cache.py             视频 JPEG 缓存
    README.md            视频参数及实现说明
    tests/               视频单元测试、应用集成测试及模拟设备
```

框架不导入视频示例，也不要求 FFmpeg。示例随源码包发布，wheel 包含 `decklet` 框架和原有 `streamdock._vendor` SDK。旧 `commands/video/` 与 `streamdock play` 已移除。

## 应用运行流程

1. CLI 加载脚本，设置脚本参数及同目录导入路径，检查导出的 `App`。加载失败不访问 USB。
2. 设备工作线程选择 M18、打开连接并安装 SDK 回调。应用循环依次执行 `on_start` 和有效的 `on_connect` 通知。
3. SDK 回调通过线程安全投递交给应用循环，规范化为按下/松开事件；应用循环串行运行生命周期、按键和定时处理函数。
4. 画面更新按逻辑键合并。单个 USB 工作线程负责 JPEG 编码、唯一一次槽位转换及发送，成功后确认该批次版本；发送中的更新不会被旧版本确认覆盖。
5. 空闲时也检查连接。断线锁定原序列号重试，清除旧连接输入，保留脚本状态及目标画面。连接恢复独立于回调调度，避免等待 `flush()` 的回调阻塞重连。
6. 退出时取消受管任务，等待当前设备操作完成，恢复底层回调并释放 USB，最后执行所有 `on_stop` 清理函数。

事件处理函数在 `await` 处让出执行，不应做阻塞调用。视频示例将解码和 SQLite 访问放在自己的工作线程；所有图片提交仍回到应用循环，底层 USB 只由运行时操作。

## 硬件适配与按键映射

设备参考配置位于 [device.py](../src/decklet/device.py)。`uv run decklet info` 输出的 `profile.logical_keys` 是从上到下、从左到右的逻辑编号，`profile.image_slots` 是对应的硬件图片槽位：

```text
逻辑按键                 硬件图片槽位
 1  2  3  4  5          11 12 13 14 15
 6  7  8  9 10           6  7  8  9 10
11 12 13 14 15           1  2  3  4  5
```

官方高层 `set_key_image` 自带映射。本项目使用底层 `set_key_image_stream` 发送内存 JPEG，因此由 `runtime.py` 在发送前转换一次，切片和用户脚本始终使用逻辑编号。参考固定 SDK 版本的[官方 M18 驱动](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDockM18.py)。

框架负责按键边沿去重；视频示例由 [controls.py](../apps/video/controls.py) 绑定底部无屏按键。

| 位置 | SDK 逻辑编号 | 硬件码 | 播放命令 |
| --- | --- | --- | --- |
| 左 | 16 | `0x25` | `rewind` |
| 中 | 17 | `0x30` | `pause` |
| 右 | 18 | `0x31` | `forward` |

逻辑编号与硬件码来自上述官方驱动；物理位置顺序沿用当前项目绑定，仍需实机核对。

固定版本 SDK 的背景 MP4 接口仅支持 N4Pro、XL、M3，M18 不在其中，所以本项目使用按键图片流。参见[官方视频接口说明](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/README.md)。

连接时避免调用会清空图标并将亮度设为 100% 的 `init()`，只调用 `set_device()` 和 `wakeScreen()`。每帧逐槽发送 JPEG，全部成功后才 `refresh()`；传输不可写超过 3 秒或发送返回非零值时停止。关闭连接使用 `close(notify=False)`。

## 缓存实现

使用方式和清理方法见[视频缓存](../apps/video/README.md#视频缓存)。实现位于 [cache.py](../apps/video/cache.py)，每份缓存为一个 SQLite 文件：

- `metadata` 表存储缓存身份和总帧数；`frames` 表以 `idx` 为主键，存储 JPEG 数据及 CRC32 校验值。
- 每帧按逻辑按键顺序存储各张 JPEG，前置四字节大端长度；读取时校验帧连续性、CRC32、长度及 JPEG 首尾标记。
- 文件名由缓存身份的 SHA-256 得到。身份包含源文件绝对路径、大小、纳秒修改时间、渲染参数、逻辑按键与图片尺寸、Pillow 版本和 `CACHE_VERSION`。
- 构造缓存身份时将 `start` 归零、`seconds` 清空；单键模式将 `gap` 归零。`loop` 不参与身份计算。
- 生成时逐帧解码、编码和写入临时数据库，完成后再次核对源文件身份，再用 `os.replace` 原子替换正式文件；中断重建保留旧缓存。
- 加载时检查元数据、帧数与索引范围，结构不完整则重建；帧内容在播放读取时校验，失败则提示 `--rebuild-cache`。

当前 `CACHE_VERSION = 2`，旧硬件槽位缓存不再复用。修改编码格式或渲染语义时应递增 `CACHE_VERSION`，避免复用不兼容缓存。

## 硬件验证范围

当前适配目标为本地配置中的 M18V25E，运行时入口仅接受 SDK 的 `StreamDockM18` 驱动实例。`info` 不探测硬件，其 `hardware_verified` 固定为 `false`，不能用它判断 USB 是否连接或实机效果是否通过。

原 README 记录曾识别本地 M18，并完成 10 秒、100 帧发送测试，程序侧无丢帧或报错；另记录用户提供的 Mirabox StreamDock 软件版本为 `3.10.205.0918`。这些是历史记录，仓库没有对应测试日志，本次文档整理未重新进行硬件验证。

设备画面效果、底部按键物理位置及实际间距仍需实机确认。自动化测试不能替代这些检查，也不能证明其他型号或系统可用。
