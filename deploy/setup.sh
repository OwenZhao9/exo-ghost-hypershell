#!/usr/bin/env bash
# 在香橙派 / 树莓派（Debian 系 Linux）上一键安装 exo-ghost。
# 用法：bash deploy/setup.sh            （在项目目录里跑）
#      bash deploy/setup.sh --no-service （不装开机自启）
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="${SUDO_USER:-$(id -un)}"
INSTALL_SERVICE=1
[[ "${1:-}" == "--no-service" ]] && INSTALL_SERVICE=0

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!!  %s\033[0m\n' "$*"; }

[[ "$(uname -s)" == "Linux" ]] || { echo "这个脚本只在 Linux 上跑（Mac 直接 uv sync 即可）"; exit 1; }

say "1/6 系统依赖"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv curl git

say "2/6 串口权限（把 $USER_NAME 加入 dialout 组）"
if ! id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx dialout; then
  sudo usermod -aG dialout "$USER_NAME"
  warn "已加入 dialout 组，需要重新登录（或重启）才生效"
fi
# 给外骨骼的 CP2102N 一个固定别名 /dev/exo，避免多设备时认错
sudo tee /etc/udev/rules.d/99-exo-ghost.rules >/dev/null <<'RULE'
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", SYMLINK+="exo", MODE="0660", GROUP="dialout"
RULE
sudo udevadm control --reload-rules && sudo udevadm trigger || true

say "3/6 安装 uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null || { echo "uv 安装失败，手动装：curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }

say "4/6 Python 依赖"
cd "$HERE"
uv sync

say "5/6 自检（无硬件也能跑）"
uv run python -m tools.fake_session --seconds 3 >/dev/null
uv run python -c "
import bridge.serial_io as m, control.policies, control.safety, tools.service, tools.webhub
print('  模块导入 OK'); print('  串口候选:', m.PORT_GLOBS); print('  找到串口:', m.find_port() or '（设备没插 / 没开机）')"

if [[ $INSTALL_SERVICE == 1 ]]; then
  say "6/6 开机自启（systemd）"
  UV_BIN="$(command -v uv)"
  sudo tee /etc/systemd/system/exo-ghost.service >/dev/null <<SERVICE
[Unit]
Description=exo-ghost 外骨骼控制服务
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$HERE
ExecStart=$UV_BIN run python -m tools.service --profile table --keepalive 0
Restart=always
RestartSec=3
StandardOutput=append:$HERE/data/service.log
StandardError=append:$HERE/data/service.log

[Install]
WantedBy=multi-user.target
SERVICE
  sudo systemctl daemon-reload
  sudo systemctl enable exo-ghost
  echo "  已注册。启动：sudo systemctl start exo-ghost"
  echo "  看日志：journalctl -u exo-ghost -f   或   tail -f $HERE/data/service.log"
else
  say "6/6 跳过开机自启"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<DONE

\033[1;32m装好了。\033[0m
  手动启动：cd $HERE && uv run python -m tools.service --profile table
  仪表盘：  http://${IP:-<本机IP>}:8000   或   http://$(hostname).local:8000
  发命令：  uv run python -m tools.ctl status / policy resist --gain 0.5 / zero / estop

  外骨骼插上后，串口固定别名是 /dev/exo（udev 规则已装）。
  若提示权限不足，重新登录一次让 dialout 组生效。
DONE
