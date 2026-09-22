"""把这几天调试踩过的坑，写成 EvoMap GEP 格式的 Capsule（验证过的修复）。

为什么要写成 Capsule 而不是写进 README：
Capsule 带**触发信号**和**审计链**，机器能按信号查到它，人能看到是谁在什么条件下
验证过。下次同样的现象再出现（无论是这台机器、别人的机器，还是下一个 Agent），
`GhostMemory.recall(信号)` 就能把当时的解法原样取回来，不用再踩一遍。

本文件是**纯数据**，不含任何 IO；播种由 `agent/memory.py` 负责。
"""
from __future__ import annotations

from evomap_genes import Capsule

#: 环境指纹：这些 Capsule 是在什么机器、什么固件上验证的。
ENV = {
    "device": "Hypershell X MaxS",
    "firmware": "2.9.99.1",
    "host_os": "darwin",
    "uart": "CP2102N (10C4:EA60) @ 3000000",
    "protocol": "FireWater / VOFA+",
}

_VERIFIED = [{"by": "exo-ghost", "at": "2026-09-22", "how": "现场复现并按步骤恢复成功"}]


def seed_capsules() -> tuple[Capsule, ...]:
    """返回要播进本地库的 Capsule。id 固定，重复播种是幂等的。"""
    return (
        Capsule(
            id="exo-usb-pd-dropout",
            title="Mac USB-C 直连三秒掉线：必须经 hub",
            trigger_signals=["串口出现后 3 秒消失", "device disconnected", "no such file or directory",
                             "/dev/cu.usbserial 反复出现消失"],
            confidence=0.95, blast_radius="single-host",
            environment=dict(ENV, link="USB-C to USB-C 直连"),
            strategy_steps=[
                "确认现象：设备节点出现约 3 秒后消失，反复循环",
                "在 Mac 与外骨骼之间插一个带供电的 USB hub",
                "重新枚举，确认 /dev/cu.usbserial-* 稳定存在超过 30 秒",
            ],
            content=(
                "Mac 的 USB-C 口会和外骨骼做 PD 供电协商，协商结果把 CP2102N 的数据通道带掉，"
                "表现为串口节点出现三秒后消失、反复循环。中间插一个 USB hub 之后不再协商，"
                "链路稳定。Linux 单板机直连没有这个问题，所以不是固件的锅。"
            ),
            verified_by=_VERIFIED, tags=["usb", "掉线", "mac", "硬件"], author="exo-ghost",
        ),
        Capsule(
            id="exo-legs-offline-recover",
            title="腿板掉线（关节角度全 0）：短按+长按恢复，不用拔线",
            trigger_signals=["ldeg=0 rdeg=0 持续", "关节数据全零", "legs_offline", "腿板掉线"],
            confidence=0.9, blast_radius="single-device", environment=dict(ENV),
            strategy_steps=[
                "确认腰部 IMU 还在动、只有 Ldeg/Rdeg/Ldps/Rdps 恒为 0，说明是腿板掉了不是串口断了",
                "力矩先清零，避免恢复瞬间有残留指令",
                "机器上电源键**短按一次，再长按**（不要拔 USB，拔线要重新枚举更慢）",
                "等 15 秒静默期：腿板上线后 3–10 秒内会有一次 35–40°、1200–1700 °/s 的自检快动",
                "静默期内不要下发任何力矩，也不要让安全层把自检快动当成急停",
            ],
            content=(
                "腿板掉线时串口仍然正常出帧，只是四个关节字段恒为 0。恢复不需要拔线："
                "电源键短按一次再长按即可让腿板重新上线。上线后 3–10 秒会自检快动一次，"
                "所以代码里把 legs_online 事件后的 15 秒设成静默期，期间强制零力矩、"
                "并用一个热身 15 秒的新 SafetyMonitor 重新取中立位。"
            ),
            verified_by=_VERIFIED, tags=["腿板", "掉线", "恢复", "静默期"], author="exo-ghost",
        ),
        Capsule(
            id="exo-port-glob-cp2102n",
            title="找不到串口：CP2102N 是 cu.usbserial-* 不是 cu.usbmodem*",
            trigger_signals=["找不到设备", "no port found", "串口扫描为空", "find_port returned None"],
            confidence=0.99, blast_radius="single-file", environment=dict(ENV),
            strategy_steps=[
                "`ls /dev/cu.*` 看实际节点名",
                "把 /dev/cu.usbserial-* 和 /dev/cu.usbmodem* 两种 glob 都加进扫描列表",
                "Linux 上对应 /dev/ttyUSB* 与 /dev/ttyACM*",
            ],
            content=(
                "这台外骨骼的 USB 转串口芯片是 Silicon Labs CP2102N（VID 0x10C4 / PID 0xEA60），"
                "在 macOS 上枚举成 /dev/cu.usbserial-XXXX。只扫 cu.usbmodem*（那是 CDC-ACM 类设备的名字）"
                "会永远找不到设备。两种 glob 都要扫，见 bridge/ports.py 的 PORT_GLOBS_DARWIN。"
            ),
            verified_by=_VERIFIED, tags=["串口", "端口发现", "cp2102n"], author="exo-ghost",
        ),
        Capsule(
            id="exo-stall-at-limit",
            title="力矩顶在机械限位上会把腿板顶掉线",
            trigger_signals=["角度到达限位不再变化", "长时间恒定力矩", "堵转", "限位 过流"],
            confidence=0.85, blast_radius="single-device",
            environment=dict(ENV, joint_range="-108° ~ +105°"),
            strategy_steps=[
                "检测：角度连续 0.35 秒几乎不变而力矩仍在下发 → 判定堵转",
                "把力矩降到 ≤ 0.5 Nm，或改用位置保持（hold）而不是恒定力矩",
                "恒定力矩命令一律带 --seconds 到期自动归零，不准无限期顶着",
            ],
            content=(
                "2026-09-22 18:49–18:53，两腿各以 1.5 Nm 顶住机械限位约三分钟后腿板掉线，"
                "现象与过流/过热保护一致。限位是 -108°~+105°。到达限位后电机速度为零、"
                "电流全部变成热量，所以代码里加了 STALL_S=0.35 的堵转检测，"
                "并且所有恒定力矩命令强制带到期时间。"
            ),
            verified_by=[{"by": "exo-ghost", "at": "2026-09-22", "how": "复现一次掉线后加入堵转检测，未再复现"}],
            tags=["堵转", "限位", "过流", "力矩"], author="exo-ghost",
        ),
        Capsule(
            id="exo-boot-bias-torque",
            title="上电自带一个微小向上保持力，做功统计要减掉",
            trigger_signals=["零力矩仍有上抬感", "自然下垂不成立", "做功统计偏大", "基础力矩"],
            confidence=0.9, blast_radius="subsystem", environment=dict(ENV),
            strategy_steps=[
                "关机对照：关机瞬间腿会松下来，说明这个力来自设备自身不是我们下发的",
                "用 tools/measure_bias.py 量出左右各自的静摩擦与偏置",
                "分析做功和对照数据时，把偏置从实测力矩里减掉",
            ],
            content=(
                "开机后髋关节本身有一个很小的向上保持力矩（左 +0.22 Nm / 右 +0.11 Nm），"
                "关机即消失，官方 App 不提供关闭开关。它会叠加在我们下发的力矩上。"
                "量级小，不影响穿戴安全，但会让'零力矩时应当自然下垂'的直觉失效，"
                "也会让做功统计偏大。另外实测破断摩擦左 0.30 Nm / 右 0.40 Nm。"
            ),
            verified_by=[{"by": "exo-ghost", "at": "2026-09-22", "how": "开关机对照 + measure_bias.py 实测"}],
            tags=["偏置", "摩擦", "标定", "做功"], author="exo-ghost",
        ),
        Capsule(
            id="exo-quiet-period-default-bug",
            title="静默期用 dict.get 默认值会把力矩永远吃掉",
            trigger_signals=["力矩恒为 0", "策略在跑但没有输出", "quiet period 永真"],
            confidence=1.0, blast_radius="single-file", environment=dict(ENV),
            strategy_steps=[
                "检查形如 `time.time() - state.get('x', 0.0) < N` 的判断",
                "键从没被设置过时默认值 0.0 会让差值变成一个巨大的数——但如果判断方向是 `<`，"
                "在'从未发生过'的语义下反而恒真/恒假，两种都是错的",
                "改成先判存在：`if state.get('x') and time.time() - state['x'] < N`",
            ],
            content=(
                "原代码 `if time.time() - state.get('legs_online_at', 0.0) < 15.0` 想表达"
                "'腿板刚上线 15 秒内静默'，但 legs_online_at 从没被设置时默认 0.0，"
                "判断退化成一个与本意无关的恒定结果，把所有力矩都吃掉了，现象是'策略在跑但输出恒为 0'。"
                "教训：用默认值把'没发生过'伪装成'很久以前发生过'是不安全的，要显式判存在。"
            ),
            verified_by=[{"by": "exo-ghost", "at": "2026-09-22", "how": "改成显式判存在后力矩恢复正常"}],
            tags=["bug", "默认值", "静默期", "python"], author="exo-ghost",
        ),
        _estop_capsule(),
    )


def _estop_capsule() -> Capsule:
    """急停之后怎么办——这是现场最容易慌的一步，必须写清楚。"""
    return Capsule(
        id="exo-estop-recovery",
        title="急停锁存后的恢复流程：先确认安全，再重新武装",
        trigger_signals=["急停", "trip", "倾角 跌倒", "锁存", "TRIPPED", "力矩被清零"],
        confidence=0.95, blast_radius="subsystem", environment=dict(ENV),
        strategy_steps=[
            "先看人：穿戴者站稳了没有，支架有没有卡住，手离开支架",
            "再看原因：终端/页面上那条急停原因写了是哪个信号超限（加速度/角速度/倾角/关节速度）",
            "原因消失之后才重新武装：`uv run python -m tools.ctl arm`，或页面上点「重新武装」",
            "重新武装会把策略强制回到 zero，并新建一个 SafetyMonitor 重新取中立位",
            "从小力矩重新开始（≤ 0.5 Nm），确认手感正常再逐步加回去",
        ],
        content=(
            "急停是锁存的：反射层只回答「这一帧安不安全」，锁存由 ExoBridge.trip 做，"
            "锁存后力矩清零并 DISABLE，必须显式重新武装才会恢复。"
            "不要一急停就直接 arm——先弄清是哪个信号触发的，原因还在的话 arm 完会立刻再停一次。"
            "重新武装会重新热身取中立位，所以 arm 之后的头两秒 assist 不出力，这是正常的。"
        ),
        verified_by=[{"by": "exo-ghost", "at": "2026-09-23", "how": "义体注入 tilt 故障复现急停并按流程恢复"}],
        tags=["急停", "恢复", "武装", "安全"], author="exo-ghost",
    )
