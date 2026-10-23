# 计数器应用

最小的 Decklet 脚本应用，展示 `on_start`、按键事件和单键绘图。

在仓库根目录运行：

```sh
uv run decklet run apps/counter/app.py
```

按屏幕键 1 加一，按底部无屏键 18 退出。设备连接、图片编码、按键去重和重连由框架管理。

应用测试位于 `tests/`，使用模拟设备，无需连接 USB。在仓库根目录执行：

```sh
uv run python -m unittest discover -s apps/counter/tests -t . -v
```

[脚本 API](../../docs/usage.md) · [视频应用](../video/README.md)
