# 功能说明与代码索引

本文件记录已经实现的行为、代码入口、数据来源与边界。功能变更时同步更新对应小节、`CHANGELOG.md` 和 `site/`；公开版本由 `site/README.md` 中的 Cloudflare Pages 项目发布。

## 控制链路与实时监视

- **行为**：本机服务通过 USB 串口读取外骨骼传感器帧，显示左右髋角度、速度和指令力矩；通过同一控制链路下发 `zero`、`resist`、`assist`、`hold`、`torque` 策略。自动发现串口并在断开后持续重试；恢复时重新确认就绪状态，不自动恢复施力。
- **入口**：`python -m runtime.service`；`python -m tools.ctl`；本机 `dashboard/index.html`。
- **关键文件**：`bridge/ports.py`、`bridge/exo.py`、`bridge/serial_io.py`、`bridge/protocol.py`、`runtime/service.py`、`runtime/commands.py`、`dashboard/app.js`。
- **数据来源**：串口真实帧；页面只显示新收到的实时帧。记录落在本机 `data/`，公开网站不读取这些私人记录。
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

- **当前状态**：交互式公开 3D 展示位于 `site/`；具备实时真机、仿真、历史实测回放三种来源区分的本机 3D 控制视图位于 `feat/auto-reconnect-GPT` 分支的 `dashboard/twin.html`、`twin.js`、`twin-config.json`。
- **素材**：`site/assets/exoskeleton.glb` 取自该分支的 Tripo 多视角生成模型；依据获准使用的 Hypershell X Max S 官方图片制作。模型仅为视觉近似，不是制造商 CAD，也不提供碰撞或安全计算。原始素材、任务和关节分组依据见该分支 `dashboard/assets/README.md`。
- **公开回放**：`site/data/twin-replay.json` 为真实设备的桌面标定记录；不能称作当前在线真机或穿戴记录。静态网站没有远程控制能力。

## 产品工作区（`integration/product-GPT` 分支）

该功能组已经在独立集成分支实现，尚未合入本文件所在主分支。公开网站介绍已完成的功能，不表示产品服务已在公开网站运行。集成分支的详细现状见 `docs/product-status.md` 与 `docs/product-branches.md`（在该分支阅读）。

| 功能 | 实现文件 | 行为与边界 |
| --- | --- | --- |
| 本机产品页面 | `product/server.py`、`dashboard/product/` | 本机默认只读；明确 `real` 来源并就绪后才允许操作控制入口。 |
| 运动模式 | `product_features/modes/` | 手动选择助力或锻炼预设；控制仍经过原有安全链路。 |
| 行走档案 | `product_features/records/` | 收录已有 CSV、区分真机/桌面/仿真来源，输出有效活动时间、双侧幅度及指令做功估计。不能推断真实肌力、省力比例。 |
| 个人记忆 | `product_features/memory/` | 保存偏好、参数版本并导出 JSON。 |
| 成长徽章 | `product_features/growth/` | 只基于完整真实穿戴记录；桌面、仿真、重复、静止或急停记录不计进度。 |

眼镜引路需要用户指定视觉 API 并完成真机验证，目前不能列为已实现。跨设备策略迁移、康复与保险结论也未实现。

## 公开宣传网站

- **入口**：`site/index.html`；样式 `site/styles.css`；3D 回放 `site/app.js`。
- **部署**：Cloudflare Pages 项目 `exo-ghost`，操作见 `site/README.md`。
- **边界**：站点为静态资源；不调用本机 WebSocket、串口、数据库或控制命令。新增功能需对应更新宣传内容，同时保留已验证状态与数据来源说明。
