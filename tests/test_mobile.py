"""手机连接的鉴权、命令白名单和断线安全租约。"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil

import pytest

from runtime.mobile import (MobileLease, is_loopback, mobile_command,
                            pairing_token, release_mobile_control, token_matches)
from runtime.session import Session
from control.safety import PROFILES
from tools.webhub import WebHub
from tools.mobile_pairing import PAIR_PREFIX, pairing_payload, write_qr
from tools.prepare_mobile_demo import write_pairing_config


def test_local_demo_pairing_config_contains_credentials_with_private_permissions(tmp_path):
    path = tmp_path / "DemoPairing.local.xcconfig"
    host = "192.168.40.25:8765"
    token = "private-pairing-token-with-more-than-32-characters"
    write_pairing_config(path, host, token)
    assert path.read_text() == f"DEMO_HOST = {host}\nDEMO_TOKEN = {token}\n"
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_pairing_qr_contains_exact_host_and_token_but_not_in_filename(tmp_path):
    host = "192.168.40.25:8765"
    token = "private-pairing-token-with-more-than-32-characters"
    payload = pairing_payload(host, token)
    assert payload.startswith(PAIR_PREFIX)
    encoded = payload.removeprefix(PAIR_PREFIX)
    data = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    assert json.loads(data) == {"v": 1, "host": host, "token": token}
    if not shutil.which("qrencode"):
        pytest.skip("qrencode 未安装")
    path = write_qr(str(tmp_path), payload)
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert token not in str(path)


def test_pairing_token_is_long_private_and_reused(tmp_path):
    path = tmp_path / "state"
    first = pairing_token(str(path))
    assert len(first) >= 32
    assert pairing_token(str(path)) == first
    assert os.stat(path / "mobile-pairing-token").st_mode & 0o777 == 0o600
    assert token_matches(first, first)
    assert not token_matches(first, first[:-1] + "x")
    assert not token_matches("", "")


def test_only_loopback_can_use_legacy_local_dashboard_path():
    assert is_loopback(("127.0.0.1", 1234))
    assert is_loopback(("::1", 1234))
    assert not is_loopback(("192.168.1.22", 1234))
    assert not is_loopback(None)


def test_mobile_commands_are_limited_and_client_metadata_cannot_be_spoofed():
    client = "trusted-client"
    assert mobile_command({"op": "arm"}, client) is None
    assert mobile_command({"op": "hold", "L": 90}, client) is None
    assert mobile_command({"op": "torque", "L": 1.5}, client) is None
    assert mobile_command({"op": "policy", "policy": "assist", "gain": 0.9, "max": 0.8}, client) is None
    assert mobile_command({"op": "policy", "policy": "assist", "gain": 0.2, "max": float("inf")}, client) is None
    assert mobile_command({"op": "estop", "_client_id": "fake"}, client) == {
        "op": "estop", "_mobile": True, "_client_id": client}
    assert mobile_command({"op": "policy", "policy": "assist", "gain": 0.2,
                           "max": 0.8, "_client_id": "fake"}, client) == {
        "op": "policy", "policy": "assist", "gain": 0.2, "max": 0.8,
        "_mobile": True, "_client_id": client}


def test_mobile_lease_expires_and_stale_heartbeat_cannot_reactivate():
    lease = MobileLease()
    lease.start("phone", now=10)
    assert not lease.clear("another")
    assert lease.refresh("phone", now=11)
    assert lease.expired(now=13)
    assert not lease.refresh("phone", now=13)
    assert lease.clear("phone")
    assert not lease.refresh("phone", now=13.1)


def test_mobile_disconnect_releases_policy_and_pending_pulse():
    class Bridge:
        def set_ramp(self, value):
            self.ramp = value

    bridge = Bridge()
    session = Session(profile=PROFILES["table"], ramp_cap_nm_s=1.5)
    from control.policies import make_policy
    session.policy = make_policy("assist", 0.2, 0.8)
    session.pulse_until = 99
    lease = MobileLease()
    lease.start("phone", now=10)
    assert not release_mobile_control(lease, session=session, bridge=bridge,
                                      log=lambda *a, **kw: None, owner="other")
    assert session.policy.name == "assist"
    assert release_mobile_control(lease, session=session, bridge=bridge,
                                  log=lambda *a, **kw: None, owner="phone")
    assert session.policy.name == "zero" and session.pulse_until == 0
    assert bridge.ramp <= 1.5


class FakeSocket:
    def __init__(self, first, commands):
        self.remote_address = ("192.168.1.22", 4000)
        self.incoming = [json.dumps(first)] + [json.dumps(c) for c in commands]
        self.sent = []
        self.closed = None

    async def recv(self):
        return self.incoming.pop(0)

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def close(self, **kwargs):
        self.closed = kwargs

    def __aiter__(self):
        self.remaining = iter(self.incoming)
        return self

    async def __anext__(self):
        try:
            return next(self.remaining)
        except StopIteration:
            raise StopAsyncIteration


def test_remote_socket_rejects_bad_token_and_forwards_only_safe_commands():
    seen = []
    hub = WebHub(seen.append, mobile_token="correct-token-with-more-than-32-characters")
    bad = FakeSocket({"op": "pair", "token": "wrong"}, [{"op": "estop"}])
    asyncio.run(hub._handler(bad))
    assert bad.closed is not None
    assert not any(c["op"] == "estop" for c in seen)

    seen.clear()
    good = FakeSocket({"op": "pair", "token": hub.mobile_token}, [
        {"op": "arm"}, {"op": "policy", "policy": "resist", "gain": 0.3, "max": 1.5},
        {"op": "heartbeat"}, {"op": "estop"}])
    asyncio.run(hub._handler(good))
    assert good.sent[0] == {"k": "paired"}
    assert [c["op"] for c in seen] == ["policy", "heartbeat", "estop", "mobile_lost"]
    assert all(c["_mobile"] for c in seen)
    assert len({c["_client_id"] for c in seen}) == 1
