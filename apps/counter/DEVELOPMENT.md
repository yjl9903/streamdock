# 计数器开发指南

## 实现

计数器代码集中在 [app.py](app.py)：`render()` 绘制数字，`@app.on_start` 显示初始画面，`@app.on_key` 处理计数和退出。设备连接、图片编码、按键去重和重连由框架管理。

计数保存在脚本的 `count` 变量中。每次按键后重新绘制并提交屏幕键 1 的画面；断线重连不会重新加载脚本，因此计数保留。按键 18 调用 `ctx.stop()` 请求退出。

## 测试

在仓库根目录运行：

```sh
uv run python -m unittest discover -s apps/counter/tests -t . -v
```

[tests/test_app.py](tests/test_app.py) 通过脚本加载器和运行时启动应用，使用模拟设备验证初始画面、连续两次计数后的画面更新及按键退出，无需连接 USB。测试同时检查逻辑键 1 经框架映射到硬件图片槽位 11。
