"""只在本机终端显示手机配对信息：python -m tools.mobile_pairing。"""
from __future__ import annotations

import argparse

from runtime.mobile import pairing_token
from tools.webhub import lan_ip


def main() -> None:
    ap = argparse.ArgumentParser(description="显示本机手机控制配对信息")
    ap.add_argument("--state-dir", default="data")
    ap.add_argument("--ws-port", type=int, default=8765)
    a = ap.parse_args()
    print(f"Mac 地址：{lan_ip()}:{a.ws_port}")
    print(f"配对口令：{pairing_token(a.state_dir)}")
    print("请只在自己的 iPhone 上输入，不要截图或分享口令。")


if __name__ == "__main__":
    main()
