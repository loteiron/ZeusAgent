# ZeusAgent

基于 Nous Research / Hermes Agent 的独立个人 AI 助手。原始 MIT 许可证和署名保留在 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md) 中。

这是开发中的源码包。安装和使用说明见 [README.md](README.md)。

## 从当前源码包安装

完整解压文件。需要 Python 3.11–3.13；构建界面还需要符合 `package.json` 要求的 Node.js 和 npm。

```sh
python scripts/setup_zeus.py --web
python scripts/launch_zeus.py setup
python scripts/launch_zeus.py
```

Linux/macOS 可使用 `python3`。Windows 可先运行 `KUR-ZEUS.bat`，安装后运行 `BASLAT-ZEUS.bat`。

桌面版：

```sh
python scripts/setup_zeus.py --desktop
python scripts/launch_zeus.py --desktop
```

正常启动使用本地构建结果。开发时使用 `--desktop-dev` 启动热更新环境。网页面板使用 `python scripts/launch_zeus.py dashboard`。

模型服务和 Telegram 需要另行配置。不会自动迁移原 Hermes 数据。目前没有 ZeusAgent 专用远程更新渠道；Hermes 的安装地址提供的是原产品。

继承的旧译文保存在 [docs/UPSTREAM-README.zh-CN.md](docs/UPSTREAM-README.zh-CN.md)，仅供历史参考。
