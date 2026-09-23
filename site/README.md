# Ghost 公开网站维护

站点由 `index.html`、`styles.css`、`app.js` 和 `assets/`、`data/`、`vendor/` 组成，无构建步骤。它只展示公开信息与真实桌面记录回放，不调用设备控制服务。

## 本地检查

在仓库根目录运行 `python3 -m http.server 8788 --directory site`，用 Chrome 打开 `http://localhost:8788/`。检查桌面、移动端导航、图片、3D 加载、回放按钮和 GitHub 链接。不要直接用 `file://` 打开，模块与数据请求需要 HTTP。

## 发布

Cloudflare Pages 项目名：`exo-ghost`；生产分支：`main`。从仓库根目录运行：

```sh
wrangler pages deploy site --project-name exo-ghost --branch main
```

部署后访问 `https://exo-ghost.pages.dev/`，确认页面和 3D 素材均可访问。Cloudflare Direct Upload 由操作人主动部署；GitHub 推送本身不会自动发布。后续每次功能完成时按 `AGENTS.md` 同步 `docs/FEATURES.md`、`CHANGELOG.md` 与站点，再执行发布并验证。

## 素材与隐私

- `assets/hypershell-*.webp`：依据用户确认获官方许可的 Hypershell X Max S 图片优化生成，原图 URL 和许可说明见 `feat/auto-reconnect-GPT` 分支的 `dashboard/assets/README.md`。
- `assets/exoskeleton.glb`：同分支 Tripo 生成的视觉模型；不是工程 CAD 或安全模型。
- `data/twin-replay.json`：真实设备桌面标定记录的抽样回放，非当前在线数据。
- `vendor/`：Three.js 与加载器本地文件，许可证见 `vendor/THREE-LICENSE`。
- 严禁将 `data/` 中的私人会话记录、密钥、实时控制 WebSocket 地址或操作命令复制到网站。
