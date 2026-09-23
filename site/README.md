# Ghost 本地展示网页

用户最新要求只在本机使用，不发布到 Cloudflare 或其他公网服务。原 Cloudflare Pages 项目 `exo-ghost` 已删除。

网页由 `index.html`、`styles.css`、`app.js` 和 `assets/`、`data/`、`vendor/` 组成，无构建步骤。它展示项目功能与真实桌面记录回放，不调用设备控制服务。

## 本地启动

在仓库根目录运行：

```sh
python3 -m http.server 8788 --bind 127.0.0.1 --directory site
```

在 Chrome 打开 `http://127.0.0.1:8788/`。不要直接用 `file://` 打开；浏览器模块和回放数据需要 HTTP。`--bind 127.0.0.1` 保证服务只在本机可访问。检查桌面、移动端导航、图片、3D 加载和回放按钮。

## 更新流程

每次功能变更，同步 `docs/FEATURES.md`、`CHANGELOG.md` 和本网页，按仓库 `AGENTS.md` 进行本机验证。不要把静态网页接入串口、实时控制 WebSocket 或私人数据库。

## 素材与隐私

- `assets/hypershell-*.webp`：依据用户确认获官方许可的 Hypershell X Max S 图片优化生成；原图 URL 和许可说明见 `feat/auto-reconnect-GPT` 分支的 `dashboard/assets/README.md`。
- `assets/exoskeleton.glb`：同分支 Tripo 生成的视觉模型，不是工程 CAD 或安全模型。
- `data/twin-replay.json`：真实设备桌面标定记录的抽样回放，并非当前在线数据。
- `vendor/`：Three.js 与加载器本地文件，许可证见 `vendor/THREE-LICENSE`。
- 不把 `data/` 中的私人会话记录、密钥、实时控制地址或操作命令复制到网页。
