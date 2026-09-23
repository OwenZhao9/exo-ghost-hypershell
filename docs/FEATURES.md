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

- **当前状态**：交互式本地 3D 展示位于 `site/`。本地网页可在只读的设备实时流与历史桌面实测记录间切换；具备实时真机、仿真、历史实测回放三种来源区分的本机 3D 控制视图位于 `feat/auto-reconnect-GPT` 分支的 `dashboard/twin.html`、`twin.js`、`twin-config.json`。
- **素材**：`site/assets/exoskeleton.glb` 取自该分支的 Tripo 多视角生成模型；依据获准使用的 Hypershell X Max S 官方图片制作。模型仅为视觉近似，不是制造商 CAD，也不提供碰撞或安全计算。原始素材、任务和关节分组依据见该分支 `dashboard/assets/README.md`。
- **本地回放**：`site/data/twin-replay.json` 为真实设备的桌面标定记录；不能称作当前在线真机或穿戴记录。展示页没有设备控制能力。
- **实时观察**：`site/live.js` 只读订阅本机 `ws://127.0.0.1:8765`，解析双髋角度、角速度、指令力矩和腰部 IMU。`site/app.js` 用有效新帧驱动外骨骼与人体髋关节；`site/motion.js` 仅在陀螺仪检测到实际转动时累积短时 yaw 变化，带动整体模型相对转身，避免静止 yaw 漂移驱动画面。双侧角度连续约两秒出现足够幅度和交替摆动时，页面标记“检测到交替摆腿”；这是髋部运动模式提示，不证明有人穿戴、脚步落地或发生前进。首帧作为视觉对齐基准，用户可按“对齐当前姿态”重新设定或关闭转身跟随，短暂断线后保留同一基准。断流或腿板失效后清空读数并停止姿态更新，每秒尝试重连。设备未标记 `body` 时仍可显示新鲜读数，但明确标为“来源未标记”；`body=sim` 时不显示为真机数据。网页不发 WebSocket 命令、不打开串口。
- **人体模型**：`site/assets/human-tripo-rigged.glb` 由 Tripo 根据白膜参考图生成并自动绑骨，呈现无五官、无发型的自然人体轮廓。参考图从获准使用的 Hypershell 官方穿戴照片提取人体比例与展示风格，未复刻照片真人身份或旧设备；生成记录见 `model-sources/README.md`，来源说明见 `site/assets/HUMAN-LICENSE.md`。`site/app.js` 移除模型贴图并使其呈半透明白色，旋转 180° 修正人物与外骨骼的前后穿戴方向，交换左右髋骨对应关系，再按髋骨位置对齐外骨骼，并以同一双髋角度驱动腿骨；可显示/隐藏。该模型仍为视觉近似，不是官方人体 3D 或精确人体扫描，膝足与手臂没有实时传感器联动。
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

眼镜引路需要用户指定视觉 API 并完成真机验证，目前不能列为已实现。跨设备策略迁移、康复与保险结论也未实现。

### 本机入口与兼容性

- **入口**：产品工作目录执行 `uv run python -m product.server`。集成分支默认端口 8110，各功能分支自动使用 8100–8105；数据默认存储在各自目录的 `data/product/product.db`。
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

- 集成分支已运行 `uv run pytest tests/ -q`：134 项通过，覆盖既有控制安全基准、串口恢复、档案来源与计算、数据库隔离、持久化、去重与徽章资格。
- `node --test tests/product-device.test.mjs`：3 项通过，覆盖启动不发命令、过期/仿真/来源不明/只读连接拒绝施力、参数边界及停止路径。
- Chrome 已验证产品页面导航、现有真机数据接收、真实桌面记录收录、产品服务重启后记录保留、桌面记录不解锁徽章。测试使用的私人记录未纳入展示页或 Git。
- 新产品页面的施力操作尚未现场验证；当前展示服务为只读。引路 API 尚缺提供商、地址、模型及密钥配置位置；人体肌力、疲劳、省力比例、里程和爬升没有已验证实现。

## 本地展示网页

- **入口**：`site/index.html`；样式 `site/styles.css`；3D 实时视图和回放 `site/app.js`、只读实时流 `site/live.js`。
- **运行**：在本机启动静态 HTTP 服务，命令见 `site/README.md`。用户已取消公网发布。
- **边界**：网页为静态资源，可只读订阅本机设备 WebSocket；不调用串口、数据库或控制命令。新增功能需对应更新展示内容，同时保留已验证状态与数据来源说明。2026-09-23 验证时控制进程带 `--body real --profile table`，Chrome 显示约 178–179 Hz 的实时双髋读数；设备静置，转身方向与真实穿戴行走尚需现场对照。旧进程未在 WebSocket 状态中标记 `body`，所以网页仍显示“来源未标记”。
