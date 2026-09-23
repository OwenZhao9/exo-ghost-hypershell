# exo-ghost

给 Hypershell X MaxS 髋关节外骨骼装一个 Ghost —— 上位机控制栈 + 实时监视器 + 安全层。

> EvoTavern 进化酒馆黑客松 · 深圳站 · 03 原生 Agent (GHOST NETWORK) 赛道

设备链路、控制策略、三层 Agent（反射 / 直觉 / 经验）、数字义体、实时监视器全部跑通，
没有真机也能完整演示。四个通用能力拆成了独立的开源库，本仓库是它们的第一个用户。

## 这是什么

外骨骼固件（2.9.99.1）由 Hypershell 固定，**本仓库不向设备烧录任何程序**。
所有代码运行在电脑上，通过 USB 串口（3 Mbps）读它每秒 180 帧的传感器数据、回发左右髋关节力矩。

```
外骨骼（真机）  或  bridge/sim.py（数字义体，参数辨识自真机录制）
   │ USB 串口 3 Mbps / 180 Hz
bridge/      收 S: 帧、100 Hz 续发 T、安全闸、断流自动重连、CSV 落盘、故障注入
   │
control/     策略（zero / resist / assist / hold / torque）+ 安全监视器
   │
agent/       ← Ghost 的三层
   │
runtime/     常驻服务：策略切换、设备事件、状态快照
   │  WebSocket
dashboard/   实时曲线 + 急停 + 事件时间线 + Ghost 三层面板（手机可开）
```

Ghost 分三层，按响应时间排：

| 层 | 周期 | 做什么 | 靠哪个库 |
|---|---|---|---|
| **反射** | 每一帧（180 Hz） | 四路阈值急停 + 助力三道渐弱，不经过任何模型 | [fly-reflex](https://github.com/OwenZhao9/fly-reflex) |
| **直觉** | 每 2 秒 | 看一段窗口判断该用什么策略，**置信度不够就不动** | [jev-decide](https://github.com/OwenZhao9/jev-decide) |
| **经验** | 遇事即查 | 设备一出问题就去翻以前踩过的坑，把处置步骤摆出来 | [evomap-genes](https://github.com/OwenZhao9/evomap-genes) |

外加一具[数字义体](https://github.com/OwenZhao9/sim2real-actuator)：真机录制辨识出的
执行器参数，没有硬件也能跑完整条链路，而且故障可以按需稳定复现。

## 快速开始

### 产品工作区（GPT 分支）

新增产品页面包含运动模式、行走档案、个人记忆和成长徽章：

```bash
uv run python -m product.server
# 集成分支默认 http://localhost:8110；各功能分支自动使用不同端口
```

产品页面使用独立数据库，默认只读且不占用串口。
使用 `--recordings-dir` 读取已有设备记录，使用 `--device-ws ws://127.0.0.1:8765` 订阅现有服务。
功能范围、真机接入和待完成项见 [产品首版进度](docs/product-status.md)，分支与接口见 [分支约定](docs/product-branches.md)。

### 原控制服务

**没有硬件也能跑**（用数字义体，一条命令）：

```bash
uv sync
uv run python -m runtime.service --body sim --profile table --autopilot
# 打开 http://localhost:8000
```

有硬件时：

```bash
uv run python -m tools.ping                        # 1. 能不能说上话
uv run python -m tools.monitor --seconds 30        # 2. 只读看 180 Hz 数据流
uv run python -m runtime.service --profile table   # 3. 常驻服务 + 仪表盘
```

`--body auto`（默认）找得到真机就用真机，找不到就自动换数字义体。

另开一个终端发命令：

```bash
uv run python -m tools.ctl policy resist --gain 0.5   # 阻尼：越快越沉
uv run python -m tools.ctl hold --right 40            # 右腿转到 40° 并保持（仅桌面）
uv run python -m tools.ctl up 1.0 --seconds 20        # 两腿同时向上
uv run python -m tools.ctl estop                      # 急停（锁存）
uv run python -m tools.ctl status
```

数字义体上还可以演给人看（真机上这几条用不着——真机的故障不用我们制造）：

```bash
uv run python -m tools.ctl gait walk                  # 挂个"穿戴者"按 1 Hz 步态走路
uv run python -m tools.ctl gait limp                  # 换成跛行：两腿相位差只有 110°
uv run python -m tools.ctl fault legs_offline         # 注入腿板掉线，看 Ghost 怎么处置
uv run python -m tools.ctl fault tilt                 # 把人"扳倒"，看反射层多久急停
uv run python -m tools.ctl recall "串口找不到"         # 让 Ghost 主动去经验库里查
```

一条完整的自主链路长这样（`--autopilot` 打开后实测）：

```
走起来  → 步态相似度 1.00 → 想选 助力，置信 0.71 → 过门槛，自动切到助力，增益 0.30
改跛行  → 两腿反相 1.0→0.33 → 置信 0.29 → 门控拦住不换策略，但增益跟着降到 0.13
站住不动 → 静止占比 1.0 → 想选 松劲，置信 0.86 → 切回松劲
腿板掉线 → 力矩清零 → 同一秒查到那条经验（相似度 0.88）→ 把四步恢复流程打出来
```

**自动驾驶默认关闭**：Ghost 只给建议，人决定采不采纳。

跑完之后出一份交付单（本地 HTML，离线可看，不上传任何地方）：

```bash
uv run python -m tools.report --open
```

里面是六节：这次跑了什么 / Ghost 判了什么、哪些没被采纳 / 出了什么事它自己怎么处置的 /
**什么没成、为什么** / 命令来自谁 / 实测包络。每条结论都只来自两个文件——
逐帧传感器 CSV 和会话流水 JSONL，没有别的来源。人为注入的故障会被明确标出来，
免得把"我们自己制造的异常"说成"设备出的问题"。

## 安全

**任何力都必须缓慢加载**，这是项目的第一条规则（见 [docs/safety-rules.md](docs/safety-rules.md)）：

- 力矩斜坡：直接力矩 1 Nm/s、位置保持 1.5、阻尼/助力 3/2；穿戴档再减半
- 位置保持目标角速度默认 15 °/s
- 软限幅 ±2 Nm（桌面）/ ±1.5 Nm（穿戴），固件硬限 ±7.5 Nm
- 急停：页面大红键 / `ctl estop` / Ctrl-C / 拔 USB（固件看门狗 115 ms 清零）
- 穿戴档额外启用加速度、陀螺、倾角、关节超速急停与会话时长上限

## 实测数据

| 项目 | 实测值 |
|---|---|
| 数据流 | 协议标称 200 Hz，**实测约 180 Hz**（主板时间戳间隔 6 ms） |
| 看门狗 | 协议 100 ms，**实测约 115 ms** |
| 静摩擦 | 左 0.30 Nm，右 0.40 Nm |
| 上电基础力矩 | 左 +0.22 Nm，右 +0.11 Nm（向上） |
| 关节量程 | 约 −108° … +105° |
| 方向约定 | 两腿同时向上 = `T,-x,+x`（左右镜像） |

方法与原始数据见 [docs/protocol.md](docs/protocol.md) 与 `data/samples/`。

## 目录

| 路径 | 内容 |
|---|---|
| `bridge/` | 协议解析（`protocol.py`）、端口发现、限幅、串口桥（`exo.py`）、数字义体（`sim.py`）、故障注入（`faults.py`）、穿戴者步态（`wearer.py`）、回放 |
| `control/` | 档位参数（`profiles.py`）、规则翻译（`reflex_rules.py`）、安全监视器（`safety.py`）、控制策略（`policies.py`） |
| `agent/` | 特征提取（`features.py`）、决策规则（`policy_rules.py`）、直觉层（`decide.py`）、经验层（`memory.py`）、经验数据（`capsules.py`） |
| `runtime/` | 常驻服务（`service.py`）、命令分发、事件翻译、状态快照 |
| `report/` | 会话交付单：`collect.py` 算数（纯）+ `render.py` 排版（纯） |
| `tools/` | 命令行入口、验机与标定工具 |
| `dashboard/` | `index.html` 结构 + `style.css` 配色 + `app.js` 曲线 + `ghost.js` 三层面板 |
| `tests/` | 122 项：安全层逐帧回归基准、协议、运行时、义体、故障、经验、决策、交付单 |
| `docs/` | 协议与实测笔记、安全规则、评分自评、方案说明 |
| `data/samples/` | 标定与测量的样本数据 |

## 已知问题

- **Mac USB-C 直连不可用**：PD 供电协商会让设备掉线，必须经 USB hub
- **腿部电机板会掉线**（关节数据全 0）：在机器上短按 + 长按电源键即可恢复，无需拔线；恢复后有 3–10 s 的自检快动，程序设了 15 s 静默期
- 设备静止数分钟后曾多次自行重启，原因待查（疑似闲置待机或电量）
- **做功预算需要重新标定**：桌面档 1.5 J/s 是"设备放桌上、本来就不该做什么功"的数。
  挂上穿戴者按 1 Hz 正常步态走起来实测 1.75 J/s，助力会被预算一直压在 0
  （穿戴档 3.0 J/s 也只是勉强）。反射层在照章办事，但这个阈值显然不是照着
  "人在走路"标的。改到多少是绑在人身上的安全决定，留给人拍板；
  仪表盘现在会写清"压着输出的是：每秒做功超预算 1.75 / 1.5 J/s"。

## 拆出来的四个库

这次比赛里四件通用的事，都做成了独立的公开库（MIT，各自有完整文档和测试），
本仓库是它们的第一个用户，不是它们的唯一用户：

| 库 | 解决的通用问题 | 测试 |
|---|---|---|
| [fly-reflex](https://github.com/OwenZhao9/fly-reflex) | 任何机器都需要一层不经过 AI 的确定性反射保护；受果蝇逃逸通路启发，另有一个脉冲网络后端，接口完全一致 | 121 |
| [sim2real-actuator](https://github.com/OwenZhao9/sim2real-actuator) | 从真机录制辨识执行器参数，做域随机化，让没有硬件时也能开发 | 143 |
| [jev-decide](https://github.com/OwenZhao9/jev-decide) | 把"让模型写段话再解析"换成"问个带类型的问题，拿到选择 + 概率 + 置信度"，核心是置信度门控 | 179 |
| [evomap-genes](https://github.com/OwenZhao9/evomap-genes) | 经验资产的存取：Gene 是可复用策略，Capsule 是验证过的修复，断网可用 | 145 |

接入过程中给其中两个提了真实的修复并发了 v0.1.1：

- `evomap-genes`：分词器只认 `[a-z0-9_]`，中文查询会被切成空 token，
  所有中文经验都搜不到。改成 CJK 按 2-gram 切分。
- `jev-decide`：`rules` 后端只接受 `state -> str`，永远 one-hot、置信度恒为 1.0，
  而没有 API key 时它是唯一可用后端——于是 `gate()` 在默认配置下形同虚设。
  现在可以返回 `{选项: 权重}`，"这次很接近"才能如实变成低置信度。

## 许可

MIT
