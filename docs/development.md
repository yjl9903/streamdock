# 开发指南

[返回 README](../README.md) · [使用指南](usage.md)

## 开发与验证

环境要求和安装方式见 [README](../README.md#安装与连接)。在仓库根目录同步依赖并运行测试：

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run python -m unittest discover -s tests -v
```

测试使用 `unittest`。硬件相关测试通过模拟对象验证发送和清理行为，无需连接设备；FFmpeg 集成测试生成临时视频，没有 `ffmpeg` 时会跳过，执行这些测试还需要 `libx264` 编码器。

自有 Python 代码使用 Ruff 检查和格式化；可运行 `uv run ruff check --fix .` 与 `uv run ruff format .` 整理代码。`_vendor` 中的 SDK 保留同步结果，不参与格式化。Ruff 版本由开发依赖和 `uv.lock` 固定，CI 执行相同检查。

| 测试文件 | 覆盖内容 |
| --- | --- |
| [test_hardware.py](../tests/test_hardware.py) | 私有 SDK 独立加载、发送失败、设备连接清理 |
| [test_update_sdk.py](../tests/test_update_sdk.py) | 重复同步、来源校验、补丁失败保护、删除文件、拒绝覆盖手改、归档路径安全 |
| [test_session.py](../tests/commands/video/test_session.py) | 断线重连、锁定原序列号、保留播放状态、按键重新绑定、退出等待 |
| [test_playback.py](../tests/commands/video/test_playback.py) | JPEG 分片和槽位、慢帧丢弃、播放节奏、管道短读 |
| [test_decoder.py](../tests/commands/video/test_decoder.py) | 真实 FFmpeg 缩放与取帧、循环解码、提前关闭、损坏媒体 |
| [test_gap.py](../tests/commands/video/test_gap.py) | 间距裁切、单键忽略间距、负值校验、预览遮罩 |
| [test_controls.py](../tests/commands/video/test_controls.py) | 按键去重、暂停时钟、暂停跳转预览、片段边界、循环和中断清理 |
| [test_cache.py](../tests/commands/video/test_cache.py) | 缓存复用与失效、源文件变化、中断重建、损坏校验、循环和跳转不重复解码或编码 |

## GitHub CI

GitHub Actions 的 `CI` 工作流在推送到 `main`、提交或更新 PR，以及手动触发时运行。配置位于 `.github/workflows/ci.yml`。

测试矩阵为 macOS、Ubuntu × Python 3.11、3.14，每组执行：

1. 安装 FFmpeg，并确认 `ffmpeg`、`ffprobe` 和 `libx264` 可用，避免集成测试因缺少 FFmpeg 被跳过。
2. 用 `uv sync --locked` 安装锁定依赖，离线校验 SDK 文件与补丁哈希，验证原生库可加载，再运行全部 `unittest` 测试。Ubuntu / Python 3.11 另外从上游下载固定版本，检查同步结果完全一致。
3. 用 `uv build --no-sources` 构建源码包和 wheel，检查源码包中的 README 和 `docs/` 与工作区一致，并核对 wheel 的平台标签、许可证、来源记录及 SDK 文件哈希。
4. 将 wheel 安装到独立虚拟环境，在仓库目录之外运行 `streamdock --help`、`play --help` 和 `info`，加载内置 SDK，验证安装包不依赖源码目录。

工作流固定 Action 提交及 uv 版本，并缓存 uv 下载内容；配置方式参考 [uv 的 GitHub Actions 集成指南](https://docs.astral.sh/uv/guides/integration/github/)。新提交会取消同一分支尚未完成的运行。CI 加载固定版本 SDK，但不枚举或连接 USB 设备，不验证实机播放，也不发布构建产物。

## 官方 SDK 版本管理

SDK 的精简运行副本位于 `src/streamdock/_vendor/mirabox/`，随源码包和 wheel 提供。普通用户只需 `uv sync --locked`，无需初始化子模块、克隆 SDK 或设置环境变量。当前上游基线为 `7f0d47fe91033b0883edf29b574a6c74ea9bed00`，精确来源以 [SOURCE.json](../src/streamdock/_vendor/mirabox/SOURCE.json) 为准。

上游直接构建的 wheel 缺少原生通信库；其 `StreamDock` 包名也会与本项目 `streamdock` 在大小写不敏感的文件系统上冲突。因此保留上游运行模块，以补丁将绝对导入改为私有命名空间。业务适配继续放在 `hardware.py`，不直接修改 SDK 副本。

### 同步到新的上游版本

先审查上游差异，选择完整的 40 位 commit，再执行：

```sh
uv run python scripts/update_sdk.py --revision <已审查的完整commit>
uv run python scripts/update_sdk.py --verify
uv run python -m unittest discover -s tests -v
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
src/streamdock/
  cli.py                 命令注册、分发及公共设备命令
  device.py              设备参考资料
  hardware.py            公共 SDK 适配和设备连接
  _vendor/mirabox/        固定版本 SDK、原生库、许可证和来源记录
  commands/
    video/
      cli.py             视频参数及播放命令入口
      controls.py        底部按键映射和线程安全事件队列
      cache.py           JPEG 帧缓存生成、校验与随机读取
      player.py          交互播放、暂停与跳转
      session.py         同一设备的断线重连与播放状态恢复
      playback.py        解码、分片、播放调度及预览
scripts/
  update_sdk.py          同步、复现和校验 SDK
  check_wheel.py         检查发行包中的 SDK 和平台标签
  sdk/                   文件清单和上游补丁
tests/
  test_hardware.py        公共设备适配测试
  test_update_sdk.py      同步、校验及失败恢复测试
  commands/video/        视频测试，见上表
docs/
  usage.md               使用指南
  development.md         本文档
```

视频功能集中在 `commands/video/`，由根 CLI 注册；对外命令为 `streamdock play VIDEO`。`media/`、`downloads/`、视频缓存、`previews/` 均不入库，规则见 [.gitignore](../.gitignore)；SDK 作为带来源记录的运行文件收录。README 同时用作 Python 包描述；源码包包含 `docs/`，配置见 [pyproject.toml](../pyproject.toml)。

## 播放流程

1. [视频 CLI](../src/streamdock/commands/video/cli.py) 解析参数；预览直接调用 FFmpeg 导出，不枚举或连接设备。
2. 设备播放由 [VideoPlayer](../src/streamdock/commands/video/player.py) 使用 `ffprobe` 读取视频时长，确定片段边界；默认先准备整段视频缓存。
3. [硬件适配层](../src/streamdock/hardware.py) 从 SDK 枚举结果中选择 M18，连接后注册按键回调。
4. 播放线程按单调时钟调度帧，发送慢时跳过过期帧。回调只把命令放入线程安全队列；暂停、跳转、解码和图片发送均由播放线程处理。
5. 结束或中断时关闭解码器和缓存读取连接、恢复原按键回调并释放设备连接。实时解码模式在跳转或循环时重新打开 FFmpeg；缓存模式通过帧索引读取 JPEG。

## 硬件适配与按键映射

设备参考配置位于 [device.py](../src/streamdock/device.py)。`uv run streamdock info` 输出的 `profile.logical_keys` 是从上到下、从左到右的逻辑编号，`profile.image_slots` 是对应的硬件图片槽位：

```text
逻辑按键                 硬件图片槽位
 1  2  3  4  5          11 12 13 14 15
 6  7  8  9 10           6  7  8  9 10
11 12 13 14 15           1  2  3  4  5
```

官方高层 `set_key_image` 自带映射。本项目使用底层 `set_key_image_stream` 发送内存 JPEG，因此在切片时转换一次，不能重复映射。参考固定 SDK 版本的[官方 M18 驱动](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/src/StreamDock/Devices/StreamDockM18.py)。

底部无屏按键由 [controls.py](../src/streamdock/commands/video/controls.py) 绑定；同一按键按住时只入队一次，松开后才接受下一次按下事件。

| 位置 | SDK 逻辑编号 | 硬件码 | 播放命令 |
| --- | --- | --- | --- |
| 左 | 16 | `0x25` | `rewind` |
| 中 | 17 | `0x30` | `pause` |
| 右 | 18 | `0x31` | `forward` |

逻辑编号与硬件码来自上述官方驱动；物理位置顺序沿用当前项目绑定，仍需实机核对。

固定版本 SDK 的背景 MP4 接口仅支持 N4Pro、XL、M3，M18 不在其中，所以本项目使用按键图片流。参见[官方视频接口说明](https://github.com/MiraboxSpace/StreamDock-Device-SDK/blob/7f0d47fe91033b0883edf29b574a6c74ea9bed00/Python-SDK/README.md)。

连接时避免调用会清空图标并将亮度设为 100% 的 `init()`，只调用 `set_device()` 和 `wakeScreen()`。每帧逐槽发送 JPEG，全部成功后才 `refresh()`；传输不可写超过 3 秒或发送返回非零值时停止。关闭连接使用 `close(notify=False)`。

## 缓存实现

使用方式和清理方法见[视频缓存](usage.md#视频缓存)。实现位于 [cache.py](../src/streamdock/commands/video/cache.py)，每份缓存为一个 SQLite 文件：

- `metadata` 表存储缓存身份和总帧数；`frames` 表以 `idx` 为主键，存储 JPEG 数据及 CRC32 校验值。
- 每帧按槽位顺序存储各张 JPEG，前置四字节大端长度；读取时校验帧连续性、CRC32、长度及 JPEG 首尾标记。
- 文件名由缓存身份的 SHA-256 得到。身份包含源文件绝对路径、大小、纳秒修改时间、渲染参数、硬件槽位、Pillow 版本和 `CACHE_VERSION`。
- 构造缓存身份时将 `start` 归零、`seconds` 清空；单键模式将 `gap` 归零。`loop` 不参与身份计算。
- 生成时逐帧解码、编码和写入临时数据库，完成后再次核对源文件身份，再用 `os.replace` 原子替换正式文件；中断重建保留旧缓存。
- 加载时检查元数据、帧数与索引范围，结构不完整则重建；帧内容在播放读取时校验，失败则提示 `--rebuild-cache`。

修改编码格式或渲染语义时应递增 `CACHE_VERSION`，避免复用不兼容缓存。

## 硬件验证范围

当前适配目标为本地配置中的 M18V25E，播放入口仅接受 SDK 的 `StreamDockM18` 驱动实例。`info` 不探测硬件，其 `hardware_verified` 固定为 `false`，不能用它判断 USB 是否连接或实机效果是否通过。

原 README 记录曾识别本地 M18，并完成 10 秒、100 帧发送测试，程序侧无丢帧或报错；另记录用户提供的 Mirabox StreamDock 软件版本为 `3.10.205.0918`。这些是历史记录，仓库没有对应测试日志，本次文档整理未重新进行硬件验证。

设备画面效果、底部按键物理位置及实际间距仍需实机确认。自动化测试不能替代这些检查，也不能证明其他型号或系统可用。
