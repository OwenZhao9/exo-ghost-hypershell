"""只在本机终端显示手机配对信息：python -m tools.mobile_pairing。"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from runtime.mobile import pairing_token
from tools.webhub import lan_ip


PAIR_PREFIX = "EXOGHOST-PAIR-V1:"


def pairing_payload(host: str, token: str) -> str:
    data = json.dumps({"v": 1, "host": host, "token": token}, separators=(",", ":"))
    return PAIR_PREFIX + base64.urlsafe_b64encode(data.encode("ascii")).decode("ascii").rstrip("=")


def write_qr(state_dir: str, payload: str) -> Path:
    if not shutil.which("qrencode"):
        raise RuntimeError("需要先安装 qrencode（brew install qrencode）")
    image = subprocess.run(["qrencode", "-o", "-", "-t", "PNG", "-s", "8", "-m", "4"],
                           input=payload.encode("ascii"), capture_output=True, check=True).stdout
    path = Path(state_dir) / "mobile-pairing-qr.png"
    with tempfile.NamedTemporaryFile(dir=state_dir, prefix=".mobile-pairing-", delete=False) as tmp:
        temp_path = Path(tmp.name)
        try:
            tmp.write(image)
            tmp.flush()
            os.fchmod(tmp.fileno(), 0o600)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    os.replace(temp_path, path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description="显示本机手机控制配对信息")
    ap.add_argument("--state-dir", default="data")
    ap.add_argument("--ws-port", type=int, default=8765)
    ap.add_argument("--qr", action="store_true", help="生成只保存在 Mac 本机的扫码配对图片")
    a = ap.parse_args()
    if not 1 <= a.ws_port <= 65535:
        ap.error("WebSocket 端口需在 1 到 65535 之间")
    host = f"{lan_ip()}:{a.ws_port}"
    token = pairing_token(a.state_dir)
    if a.qr:
        path = write_qr(a.state_dir, pairing_payload(host, token))
        print(f"扫码配对图片：{path.resolve()}")
        print(f"Mac 地址：{host}")
        print("图片包含配对口令，仅在本机展示；现场结束后可删除图片。")
    else:
        print(f"Mac 地址：{host}")
        print(f"配对口令：{token}")
        print("请只在自己的 iPhone 上输入，不要截图或分享口令。")


if __name__ == "__main__":
    main()
