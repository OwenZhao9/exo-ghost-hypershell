# exo-ghost

给 Hypershell X MaxS 髋关节外骨骼装一个 Ghost —— 上位机控制栈 + 实时监视器 + 安全层。

> EvoTavern 进化酒馆黑客松 · 深圳站 · 03 原生 Agent (GHOST NETWORK) 赛道
> 目前是 Day 2 结束时的状态：设备链路、控制策略、安全层、监视器已跑通；Agent 决策层与经验继承在 Day 3 接入。

## 这是什么

外骨骼固件（2.9.99.1）由 Hypershell 固定，**本仓库不向设备烧录任何程序**。
所有代码运行在电脑上，通过 USB 串口（3 Mbps）读它每秒 180 帧的传感器数据、回发左右髋关节力矩。

```
外骨骼 ⇄ USB 串口
   │
bridge/      收 S: 帧、200/100 Hz 续发 T、安全闸、断流自动重连、CSV 落盘、回放
   │
control/     策略（zero / resist / assist / hold / torque）+ 安全监视器
   │  WebSocket
tools/service.py   常驻服务（策略切换、事件、状态）
   │
dashboard/   浏览器实时曲线 + 急停 + 事件时间线（手机可开）
```

## 快速开始

```bash
uv sync
uv run python -m tools.ping                      # 1. 能不能说上话
uv run python -m tools.monitor --seconds 30      # 2. 只读看 180 Hz 数据流
uv run python -m tools.service --profile table   # 3. 常驻服务 + 仪表盘 localhost:8000
```

另开一个终端发命令：

```bash
uv run python -m tools.ctl policy resist --gain 0.5   # 阻尼：越快越沉
uv run python -m tools.ctl hold --right 40            # 右腿转到 40° 并保持（仅桌面）
uv run python -m tools.ctl up 1.0 --seconds 20        # 两腿同时向上
uv run python -m tools.ctl estop                      # 急停（锁存）
uv run python -m tools.ctl status
```

没有硬件时：

```bash
uv run python -m tools.fake_session --seconds 10      # 造假步态数据
# bridge/replay.py 的 ReplayBridge 与 ExoBridge 接口一致
```

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
| `bridge/` | 串口桥（`serial_io.py`）、回放（`replay.py`） |
| `control/` | 控制策略（`policies.py`）、安全监视器（`safety.py`） |
| `tools/` | 常驻服务、命令行、验机与标定工具 |
| `dashboard/` | 实时监视器网页 |
| `docs/` | 协议与实测笔记、安全规则、评分自评、方案说明 |
| `data/samples/` | 标定与测量的样本数据 |

## 已知问题

- **Mac USB-C 直连不可用**：PD 供电协商会让设备掉线，必须经 USB hub
- **腿部电机板会掉线**（关节数据全 0）：在机器上短按 + 长按电源键即可恢复，无需拔线；恢复后有 3–10 s 的自检快动，程序设了 15 s 静默期
- 设备静止数分钟后曾多次自行重启，原因待查（疑似闲置待机或电量）

## 许可

MIT
