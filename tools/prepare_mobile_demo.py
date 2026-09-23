"""Create a local, ignored pairing resource for a private iOS demo build."""
from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from runtime.mobile import pairing_token
from tools.webhub import lan_ip


def write_pairing_config(path: Path, host: str, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"DEMO_HOST = {host}\nDEMO_TOKEN = {token}\n".encode("ascii")
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".DemoPairing-", delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            tmp.write(payload)
            tmp.flush()
            os.fchmod(tmp.fileno(), 0o600)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare private pairing data for a local iOS build")
    parser.add_argument("--state-dir", default="data")
    parser.add_argument("--ws-port", type=int, default=8765)
    parser.add_argument("--output", type=Path,
                        default=Path("ios/GhostMobile/DemoPairing.local.xcconfig"))
    args = parser.parse_args()
    if not 1 <= args.ws_port <= 65535:
        parser.error("WebSocket port must be between 1 and 65535")
    host = f"{lan_ip()}:{args.ws_port}"
    write_pairing_config(args.output, host, pairing_token(args.state_dir))
    print(f"Prepared local pairing resource for {host}: {args.output}")
    print("The resource contains a secret and must never be committed or shared.")


if __name__ == "__main__":
    main()
