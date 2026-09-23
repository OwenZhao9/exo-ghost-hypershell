# 功能说明与代码索引

本文件记录已经实现的行为、代码入口、数据来源与边界。功能变更时同步更新对应小节、`CHANGELOG.md` 和本地展示网页 `site/`；运行方法见 `site/README.md`。

## 控制链路与实时监视

- **行为**：本机服务通过 USB 串口读取外骨骼传感器帧，显示左右髋角度、速度和指令力矩；通过同一控制链路下发 `zero`、`resist`、`assist`、`hold`、`torque` 策略。自动发现串口并在断开后持续重试；恢复时重新确认就绪状态，原策略回到 `zero`。
- **入口**：`python -m runtime.service`；`python -m tools.ctl`；本机 `dashboard/index.html`。
- **关键文件**：`bridge/ports.py`、`bridge/exo.py`、`bridge/serial_io.py`、`bridge/protocol.py`、`runtime/service.py`、`runtime/commands.py`、`dashboard/app.js`。
- **数据来源**：串口真实帧；页面只显示新收到的实时帧。记录落在本机 `data/`，展示网页不读取这些私人记录。
- **安全约束**：斜坡、软限幅、穿戴档加严、急停锁存、腿板掉线静默期；串口重连后不恢复旧策略。显式启用的自动策略或保活在就绪后仍按各自配置工作。详见 `docs/safety-rules.md`。
- **验证**：`tests/test_protocol.py`、`tests/test_real_reconnect.py`、`tests/test_runtime.py`、`tests/test_safety_regression.py`；真机连接状态需现场复核。

### 串口持续恢复（`feat/auto-reconnect-GPT` 分支）

- **启动与换口**：默认 `--body real`；未插设备时仪表盘仍可启动，后台持续枚举串口并握手，不自动改用仿真。恢复不再有 40 次上限；启动后才插入设备，也会继续监测后续断线。`--body sim` 与 `--body auto` 保留显式选择入口。
- **曲线与控制**：新帧到达后恢复真实曲线，断流清除旧曲线，缺失读数不伪装为零。串口重连清除旧策略和脉冲，保留 15 秒零指令等待期；等待中继续显示数据，但不接受需要施力的新控制命令。
- **腿板状态**：“腿板掉线”是双侧角度与角速度四项连续 180 帧全零的推断，单纯角速度为零不会触发；串口在线不等于关节传感器已恢复。
- **可选保活**：`--keepalive 60` 默认关闭；显式启用后，闲置时给左腿短暂力矩脉冲，仍受斜坡和限幅约束，在 `zero` 下也可能产生真实运动。它不是角度保持；防止待机或关机的效果尚未验证。
- **已验证**：完整 Python 测试 126 项通过，包含无端口启动后首次连接、再次断流换口恢复和目标归零。桌面真机已检查约 180 Hz 实时数据、一次自然断流后的恢复记录及保活脉冲后归零；尚未完成反复物理换口/重启压力测试及穿戴恢复验证。
- **详细说明**：[串口发现、持续恢复与保活](serial-recovery.md)；实现入口为 `bridge/exo.py`、`bridge/ports.py`、`runtime/service.py`、`runtime/status.py`、`dashboard/app.js`、`tools/ctl.py`。

### iPhone 控制端（`feat/ios-mobile-GPT` 分支）

- **入口与状态**：`ios/GhostMobile/` 是最低 iOS 16 的 SwiftUI App。已完成本机编译、发行签名 IPA 导出及 TestFlight 内部测试分发；尚未在用户的 iPhone 8 上安装或实测。Mac 控制服务仍独占串口，手机使用同一局域网接收真实帧、显示双侧角度曲线并发送受限命令。
- **配对和数据**：`tools/mobile_pairing.py --qr` 可在 Mac 本机生成包含当前局域网地址与口令的二维码；iPhone App 的 `PairingScanner.swift` 扫描并校验格式，一次导入后将地址存本机设置、口令存 Keychain，并尝试连接。地址变化时可重扫；手动输入仍可用。`runtime/mobile.py` 将口令以 0600 权限保存在本机 `data/`，`tools/webhub.py` 要求非本机 WebSocket 先配对，仅广播已有真实数据，拒绝未配对访问和超出手机白名单的命令。口令和二维码均不进 Git，二维码文件权限为 0600。
- **控制约束**：手机只提供低增益阻尼、轻助力、松劲和急停；无远程重新武装、保持角度及恒定力矩。`runtime/service.py` 仍检查真机来源、已武装、腿板在线、≥50 Hz 和静默期。手机租约每 2 秒必须收到心跳，断线或过期会清掉策略并回到 `zero`。操作者须继续遵守 `docs/safety-rules.md`。
- **验证与未完成**：`tests/test_mobile.py` 覆盖配对、扫码载荷、鉴权、白名单和断线租约；扫码版完整 Python 回归 133 项通过。Xcode 26.4 构建的 `1.0 (1)` 和扫码版 `1.0 (2)` 均已上传 TestFlight 并分配给只含账户持有人的内部测试群组。二维码已用 Mac Vision 识别验证，相机权限拒绝路径已在模拟器检查。仍缺 iPhone 8 实机扫描、真实连接和控制验证。局域网 WebSocket 仍为明文，限可信 Wi-Fi，不支持公网远程控制。具体操作见 [iPhone 工程说明](../ios/GhostMobile/README.md)。

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

- **入口**：`site/index.html`；样式 `site/styles.css`；3D 回放 `site/app.js`。
- **运行**：在本机启动静态 HTTP 服务，命令见 `site/README.md`。用户已取消公网发布。
- **边界**：网页为静态资源；不调用本机 WebSocket、串口、数据库或控制命令。新增功能需对应更新展示内容，同时保留已验证状态与数据来源说明。
