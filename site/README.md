# Ghost 本地展示网页

用户最新要求只在本机使用，不发布到 Cloudflare 或其他公网服务。原 Cloudflare Pages 项目 `exo-ghost` 已删除。

网页由 `index.html`、`styles.css`、`app.js`、`live.js` 和 `assets/`、`data/`、`vendor/` 组成，无构建步骤。它可只读订阅本机设备数据，也可查看真实桌面记录回放。

## 本地启动

在仓库根目录运行：

```sh
python3 -m http.server 8788 --bind 127.0.0.1 --directory site
```

在 Chrome 打开 `http://127.0.0.1:8788/`。不要直接用 `file://` 打开；浏览器模块和回放数据需要 HTTP。`--bind 127.0.0.1` 保证服务只在本机可访问。检查桌面、移动端导航、图片、3D 加载和回放按钮。

## 更新流程

每次功能变更，同步 `docs/FEATURES.md`、`CHANGELOG.md` 和本网页，按仓库 `AGENTS.md` 进行本机验证。网页的设备数据连接仅限只读 `ws://127.0.0.1:8765`；不要在展示页接入串口、发送控制命令或访问私人数据库。

经验卡介绍的是控制服务的可选 EvoMap 公开检索：需要在控制服务显式使用 `--evomap-read` 才会运行。展示网页本身不访问 EvoMap、不发送设备事件，也不展示外部条目内容。

## 实时视图

页面默认选择“实时数据”，但仅在本机设备服务送来新鲜有效数据时显示角度、角速度、指令力矩并驱动 3D 外骨骼与人体。设备离线、腿板失效、仿真来源或超过 1.5 秒没有新帧时，读数留空，模型停止更新；WebSocket 每秒尝试重连。旧控制服务未报告 `body` 来源时，页面会标明“来源未标记”。“历史记录”模式单独播放桌面标定记录，不代表当前设备正在运动。验证期间服务曾报告 `TRIPPED`、`legs_offline=true`，随后自动恢复到约 178–179 Hz；控制进程启动参数为 `--body real --profile table`，但网页仍按实际收到的 WebSocket 字段显示来源未标记。设备静置，真机动作联动尚需现场运动验证。

3D 姿态默认以首次有效双髋角度为视觉基准，之后使用实时角度差驱动左右腿。点击“对齐当前姿态”可将当下的实体姿态与模型初始姿态重新对齐；断线重连不会擅自重置基准。这个对齐只改变网页显示，不向设备发送指令，也不是对传感器或工程几何的绝对标定。

## 素材与隐私

- `assets/hypershell-*.webp`：依据用户确认获官方许可的 Hypershell X Max S 图片优化生成；原图 URL 和许可说明见 `feat/auto-reconnect-GPT` 分支的 `dashboard/assets/README.md`。
- `assets/exoskeleton.glb`：同分支 Tripo 生成的视觉模型，不是工程 CAD 或安全模型。
- `assets/human-rigged.glb`：Cesium Rigged Figure，CC BY 4.0；在网页中调整透明度、比例和髋部姿态。详见 `assets/HUMAN-LICENSE.md`。这是简化人体外形，可替换成用户提供的写实模型。
- `data/twin-replay.json`：真实设备桌面标定记录的抽样回放，并非当前在线数据。
- `vendor/`：Three.js 与加载器本地文件，许可证见 `vendor/THREE-LICENSE`。
- 不把 `data/` 中的私人会话记录、密钥、实时控制地址或操作命令复制到网页。
