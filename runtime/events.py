"""设备事件 → 人能读懂的话。

**纯映射，无状态**。事件名由 `bridge.exo.ExoBridge._emit` 发出。
"""
from __future__ import annotations

# 事件名 → (给人看的说明, 级别)。级别用于仪表盘配色：info / ok / warn / err
EVENT_MESSAGES: dict[str, tuple[str, str]] = {
    "legs_offline": (
        "腿部电机板掉线（关节全 0）→ 力矩置零；"
        "恢复：机器上短按+长按电源键（不用拔线），等 15 秒静默期", "warn"),
    "legs_online": ("腿部电机板恢复", "ok"),
    "stall": ("数据流中断，重连中…", "warn"),
    "reconnected": ("串口已重连并重新 ENABLE", "ok"),
    "stream_slow": ("数据流变慢（设备可能正在重启）→ 力矩已清零，观察中…", "warn"),
    "device_lost_enable": ("设备丢失使能（可能重启过），重新 ENABLE…", "warn"),
    "reconnect_failed": ("重连失败", "err"),
}

LEGS_ONLINE_QUIET_S = 15.0   # 腿板上线后的静默期：不出力、不判定
LEGS_ONLINE_HINT = (
    "腿板上线：15 秒静默期（不出力、不判定），期间支架可能自检快动一次，手不要放在支架旁")
TRIP_HINT = "（确认安全后：uv run python -m tools.ctl arm 或页面上点“重新武装”）"


def describe(ev: str) -> tuple[str, str]:
    """把事件名翻成 (说明, 级别)。未知事件原样返回。"""
    if ev.startswith("trip:"):
        return f"!!! 急停锁存：{ev[5:]}   {TRIP_HINT}", "err"
    return EVENT_MESSAGES.get(ev, (ev, "info"))
