# 功能说明与代码索引

本文件记录已经实现的行为、代码入口、数据来源与边界。功能变更时同步更新对应小节、`CHANGELOG.md` 和本地展示网页 `site/`；运行方法见 `site/README.md`。

## 控制链路与实时监视

- **行为**：本机服务通过 USB 串口读取外骨骼传感器帧，显示左右髋角度、速度和指令力矩；通过同一控制链路下发 `zero`、`resist`、`assist`、`hold`、`torque` 策略。自动发现串口并在断开后持续重试；恢复时重新确认就绪状态，不自动恢复施力。
- **入口**：`python -m runtime.service`；`python -m tools.ctl`；本机 `dashboard/index.html`。
- **关键文件**：`bridge/ports.py`、`bridge/exo.py`、`bridge/serial_io.py`、`bridge/protocol.py`、`runtime/service.py`、`runtime/commands.py`、`dashboard/app.js`。
- **数据来源**：串口真实帧；页面只显示新收到的实时帧。记录落在本机 `data/`，展示网页不读取这些私人记录。
- **安全约束**：斜坡、软限幅、穿戴档加严、急停锁存、腿板掉线静默期；重连后不自动恢复模式。详见 `docs/safety-rules.md`。
- **验证**：`tests/test_protocol.py`、`tests/test_real_reconnect.py`、`tests/test_runtime.py`、`tests/test_safety_regression.py`；真机连接状态需现场复核。

## Ghost 三层 Agent

- **反射 / fly-reflex**：`control/reflex_rules.py`、`control/safety.py` 逐帧检查，异常时减弱输出或急停。不能让模型推理阻塞读线程。
- **直觉 / jev-decide**：`agent/features.py`、`agent/policy_rules.py`、`agent/decide.py` 计算短时间窗口的策略建议；置信度不足时维持原策略。自动执行默认关闭。
- **经验 / evomap-genes**：`agent/memory.py`、`agent/capsules.py` 存取问题处理经验；数据库操作放在后台线程，不能阻塞设备读线程。
- **验证**：`tests/test_reflex_backends.py`、`tests/test_decide.py`、`tests/test_memory.py`。各独立库的版本和测试在各自仓库维护。

## Sim to Real 与会话交付单

- **行为**：`bridge/sim.py` 使用从真机记录辨识的执行器参数，供无硬件时运行控制链路；`bridge/wearer.py` 提供运动学步态；`bridge/faults.py` 可注入可复现故障。仿真不是人体动力学验证，不能当作真机安全结论。
- **报告**：`report/collect.py`、`report/render.py` 从本机会话 CSV 与 JSONL 生成可追溯交付单；入口 `python -m tools.report`。
- **验证**：`tests/test_sim_body.py`、`tests/test_faults.py`、`tests/test_report.py`。

## 3D 外骨骼视图

- **当前状态**：交互式本地 3D 展示位于 `site/`；具备实时真机、仿真、历史实测回放三种来源区分的本机 3D 控制视图位于 `feat/auto-reconnect-GPT` 分支的 `dashboard/twin.html`、`twin.js`、`twin-config.json`。
- **素材**：`site/assets/exoskeleton.glb` 取自该分支的 Tripo 多视角生成模型；依据获准使用的 Hypershell X Max S 官方图片制作。模型仅为视觉近似，不是制造商 CAD，也不提供碰撞或安全计算。原始素材、任务和关节分组依据见该分支 `dashboard/assets/README.md`。
- **本地回放**：`site/data/twin-replay.json` 为真实设备的桌面标定记录；不能称作当前在线真机或穿戴记录。展示页没有设备控制能力。
- **浏览器加载**：模型内嵌贴图由浏览器以 `blob:` 地址解码；模型加载后隐藏预览图。本地静态服务器不需要 Cloudflare `_headers`。

## 产品工作区（`integration/product-GPT` 分支）

该功能组已经在独立集成分支实现并推送，代码提交 `9e7996a`；尚未合入 `main`。本说明在主分支和产品分支同步维护。本地展示网页介绍已完成的功能，不表示产品服务在展示页运行。详细现状见集成分支的 `docs/product-status.md` 与 `docs/product-branches.md`。

| 功能 | 实现文件 | 行为与边界 |
| --- | --- | --- |
| 本机产品页面 | `product/server.py`、`product/workspace.py`、`dashboard/product/` | 各 worktree 默认使用独立端口与数据库；本机默认只读。明确 `real` 来源、数据新鲜且就绪后才允许经显式开启的控制入口操作。 |
| 运动模式 | `product_features/modes/` | 手动选择助力或锻炼预设；控制仍经过原有安全链路。 |
| 行走档案 | `product_features/records/` | 收录已有设备 CSV；仿真记录不进入产品档案。真机桌面、穿戴与来源未确认的记录分别标识，输出有效记录/活动时间、双侧幅度及指令做功估计。不能推断真实肌力、省力比例。 |
| 个人记忆 | `product_features/memory/` | 保存偏好、参数版本并导出 JSON。 |
| 成长徽章 | `product_features/growth/` | 只基于完整真实穿戴记录；桌面、仿真、重复、静止或急停记录不计进度。 |
| 眼镜看一看（试验） | `product_features/guide/` | 从指定的 Luma 眼镜照片目录只读列出 JPEG；用户点击单张照片后才请求 EvoMap Gateway 描述。显示文件时间，超过 30 秒的照片标识为历史照片。已用 E06-0194 真机新拍的照片完成本地保存、页面列出、网关图像透传与文字描述验收；拍照仍由独立命令手动触发。不提供连续视觉、实际引路或外骨骼动作。 |

**产品界面**：`dashboard/product/style.css`、`app.js` 和 `product_features/modes/view.js` 采用参考 DJI Fly 官网的浅色工作区、常驻功能导航、设备正面图、显眼的当前数据状态、紧凑的真实穿戴记录统计及分区清晰的模式/曲线区域。首页设备图复用项目已获准使用的 `site/assets/hypershell-front.webp`，不作为设备状态。首页状态仅使用设备服务当前消息，来源未知时明确标识；曲线无新帧时仍为空，不绘制示例数据。样式更新没有修改控制条件、设备命令或历史记录计算。设计参考与取舍见 `docs/product-ui-reference.md`。

眼镜照片描述使用 EvoMap Gateway 的 `evomap-gemini-3.1-pro-preview`。已创建仅绑定该模型、30 天到期的 Key。2026-09-23 已从当前 E06-0194 真机经 BLE 握手、拍照并保存 368×480 JPEG，再由产品页面手动发送这张照片并收到完整中文描述。眼镜音频输出、连续环境感知和实际引路尚未实现。跨设备策略迁移、康复与保险结论也未实现。

### 本机入口与兼容性

- **入口**：产品工作目录执行 `uv run python -m product.server`。集成分支默认端口 8110，各功能分支自动使用 8100–8105；数据默认存储在各自目录的 `data/product/product.db`。
- **眼镜照片入口**：使用 `--glasses-dir /Users/owenzhao/eyeGalss/shots` 只读列出 Luma 眼镜采集的 JPEG。Gateway Key 保存在本机 Git 忽略的 `data/product/evomap_gateway.key`（0600）；启动时执行 `EVOMAP_GATEWAY_API_KEY="$(cat data/product/evomap_gateway.key)" uv run python -m product.server --glasses-dir /Users/owenzhao/eyeGalss/shots`，按需附加既有 `--recordings-dir` 和 `--device-ws` 参数。点击“描述这张照片”才会将所选照片发送给 EvoMap。照片、Key 和描述结果不写入展示网页或 Git。
- **独立运行**：产品服务不打开串口、不启动仿真。通过 `--recordings-dir` 只读收录已有设备记录；指定 `--device-ws` 后订阅既有控制服务。默认不发送控制命令。
- **控制条件**：启用 `--control` 后，设备必须明确报告 `body=real`、状态 `ARMED`、数据流至少 50 Hz，且传感器与状态消息保持新鲜。断线、静默期、急停或来源不明时拒绝开始运动；松劲、急停保留独立停止路径。
- **旧服务兼容**：旧控制服务仍可供产品页面显示曲线。缺少 `body` 标记时，产品无法确认真机来源，因此不开放运动操作。切换控制服务需先释放真实串口，再从集成版本启动；不能同时运行两个控制进程。
- **关键实现**：`dashboard/product/device.js` 管理连接、过期数据和命令边界；集成分支 `runtime/status.py`、`runtime/service.py` 补充实际 `body` 与 `profile` 来源标记。未改安全阈值与力矩斜坡。

### 档案、记忆与成长的数据范围

- **档案计算**：`records/metrics.py` 从传感器 CSV 按有效时间间隔计算时长、双侧幅度、指令做功及每分钟平均绝对角速度。无效帧和断流不跨段积分；指令做功不等同于人体代谢、肌力或节省的体力。记录按内容摘要去重，原始 CSV 不被改写。
- **来源确认**：`records/importer.py` 使用配套 JSONL 的真实设备/穿戴档/结束标记确认成长资格。无法确认的旧记录可以回看，但不计入穿戴成果；路线由用户标记，未匹配相同模式与参数时不推断能力提升。
- **个人记忆**：本机保存称呼、运动目标、使用感受；每套参数保存为历史版本，重复保存相同最新版本不增加版本号。导出为 JSON，保存与导出都不自动下发参数。
- **四枚徽章**：第一步（一次至少 30 秒的有效穿戴活动）、三日同行（3 个不同日期）、一小时积累（累计 60 分钟）、左右同行（3 次至少一分钟、幅度比达到 90%）。具体规则见 `growth/rules.py`；桌面、仿真、不完整、急停、静止及重复记录不增加进度。幅度比不是医疗结论。

### 实际验证与未完成项

- 集成分支已运行 `uv run pytest tests/ -q`：139 项通过，覆盖既有控制安全基准、串口恢复、档案来源与计算、数据库隔离、持久化、去重、徽章资格及眼镜网关请求边界。
- `node --test tests/product-device.test.mjs`：3 项通过，覆盖启动不发命令、过期/仿真/来源不明/只读连接拒绝施力、参数边界及停止路径。
- Chrome 已验证产品页面导航、现有真机数据接收、真实桌面记录收录、产品服务重启后记录保留、桌面记录不解锁徽章。测试使用的私人记录未纳入展示页或 Git。
- Chrome 已检查新版总览、运动模式、档案、偏好和徽章页面；390px 手机视口下页面没有水平溢出。页面仍使用原有实时数据链路，样式调整没有通过产品页下发施力指令。
- 新产品页面的施力操作尚未现场验证；当前展示服务为只读。眼镜照片描述已通过请求封装、安全边界和 E06-0194 真机新拍 JPEG 的页面识别；拍照命令位于独立眼镜项目，网页不会自动控制眼镜。眼镜音频尚未验收。EvoMap 网关偶发模型拥堵或超时，页面会显示错误，不把失败输出用于引路。人体肌力、疲劳、省力比例、里程和爬升没有已验证实现。

## 本地展示网页

- **入口**：`site/index.html`；样式 `site/styles.css`；3D 回放 `site/app.js`。
- **运行**：在本机启动静态 HTTP 服务，命令见 `site/README.md`。用户已取消公网发布。
- **边界**：网页为静态资源；不调用本机 WebSocket、串口、数据库或控制命令。新增功能需对应更新展示内容，同时保留已验证状态与数据来源说明。
