"""手机局域网控制的配对口令与短时施力租约。纯逻辑不触碰设备。"""
from __future__ import annotations

import hmac
import math
import os
import secrets
import time
from collections.abc import Mapping

LEASE_SECONDS = 2.0


def pairing_token(state_dir: str) -> str:
    """口令只放在本机状态目录，首次运行原子创建，权限为 0600。"""
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, "mobile-pairing-token")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        with open(path, encoding="ascii") as f:
            token = f.read().strip()
        if len(token) < 32:
            raise ValueError("手机配对口令无效，请在服务停止后重新生成")
        os.chmod(path, 0o600)
        return token
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w", encoding="ascii") as f:
        f.write(token + "\n")
    return token


def token_matches(expected: str, received: object) -> bool:
    return len(expected) >= 32 and isinstance(received, str) and hmac.compare_digest(expected, received)


def is_loopback(peer: object) -> bool:
    if not isinstance(peer, tuple) or not peer:
        return False
    return peer[0] in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}


def mobile_command(raw: object, client_id: str) -> dict | None:
    """远端白名单；绝不信任客户端传来的来源标记或任意控制参数。"""
    if not isinstance(raw, Mapping):
        return None
    op = raw.get("op")
    base = {"_mobile": True, "_client_id": client_id}
    if op in {"heartbeat", "zero", "estop"}:
        return {**base, "op": op}
    if op != "policy" or raw.get("policy") not in {"resist", "assist"}:
        return None
    policy = raw["policy"]
    try:
        gain = float(raw["gain"])
        max_torque = float(raw["max"])
    except (KeyError, TypeError, ValueError):
        return None
    limit_gain = 0.3 if policy == "resist" else 0.2
    limit_torque = 1.5 if policy == "resist" else 0.8
    if not (math.isfinite(gain) and math.isfinite(max_torque)
            and 0 < gain <= limit_gain and 0 < max_torque <= limit_torque):
        return None
    return {**base, "op": op, "policy": policy, "gain": gain, "max": max_torque}


class MobileLease:
    def __init__(self) -> None:
        self.owner: str | None = None
        self.deadline = 0.0

    def start(self, owner: str, now: float | None = None) -> None:
        self.owner = owner
        self.deadline = (time.monotonic() if now is None else now) + LEASE_SECONDS

    def refresh(self, owner: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if self.owner != owner or now >= self.deadline:
            return False
        self.deadline = now + LEASE_SECONDS
        return True

    def clear(self, owner: str | None = None) -> bool:
        if self.owner is None or (owner is not None and owner != self.owner):
            return False
        self.owner = None
        self.deadline = 0.0
        return True

    def expired(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.owner is not None and now >= self.deadline


def release_mobile_control(lease: MobileLease, *, session, bridge, log,
                           owner: str | None = None) -> bool:
    """失联时让原策略回到 zero，并取消待发保活脉冲。"""
    if not lease.clear(owner):
        return False
    from runtime import commands

    session.pulse_until = 0.0
    commands.apply({"op": "zero"}, session=session, bridge=bridge, log=log)
    return True
