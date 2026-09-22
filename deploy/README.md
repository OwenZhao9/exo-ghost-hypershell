# 部署到香橙派 / 树莓派

把整套上位机（串口桥 + 控制环 + 安全闸 + 仪表盘）搬到贴身的小电脑上，
**控制环全程有线，WiFi 只传曲线和命令**——网断了力矩策略照常跑，不会一顿一顿。

```
外骨骼 ──USB-A 转 Type-C 数据线──> 香橙派 Zero 3（腰包，充电宝供电）
                                     ├ 串口桥 + 控制环 + 安全闸   ← 有线
                                     ├ HTTP :8000   仪表盘
                                     └ WebSocket :8765  广播 / 收命令
                                            ↕ WiFi（约 72 kbps）
                             Mac 浏览器 · 手机浏览器 · 大屏
```

## 一、先在 Mac 上准备好卡

1. 下载镜像：香橙派 Zero 3 用 **Debian/Ubuntu 服务器版**（官网 或 Armbian）；树莓派用 **Raspberry Pi OS Lite (64-bit)**
2. 用 [Raspberry Pi Imager](https://www.raspberrypi.com/software/) 烧卡（香橙派也能用，选「Use custom」指定镜像）
3. **烧之前点齿轮图标预设好**（关键，否则板子上不了网你也进不去）：
   - 主机名：`exo`
   - 开启 SSH，设用户名密码
   - **填好 WiFi 名和密码**，国家选 `CN`
4. 卡插进板子，接上 Type-C 电源，等 1–2 分钟

## 二、连上去

```bash
ssh <你设的用户名>@exo.local        # 找不到就用路由器后台查 IP：ssh user@192.168.x.x
```

## 三、装

```bash
git clone https://github.com/OwenZhao9/exo-ghost-hypershell.git exo-ghost
cd exo-ghost
bash deploy/setup.sh
```

脚本做六件事：装系统依赖 → 加串口权限 + 装 udev 规则（给外骨骼固定别名 `/dev/exo`）
→ 装 uv → 装 Python 依赖 → 无硬件自检 → 注册 systemd 开机自启。

**装完必须重新登录一次**（`exit` 再 `ssh` 进来），串口权限才生效。

## 四、验

```bash
uv run python -m tools.ping                  # PONG + 固件版本
uv run python -m tools.monitor --seconds 20  # 看 180 Hz 数据流
```

## 五、跑

```bash
sudo systemctl start exo-ghost     # 开机自启已注册，这次手动起
sudo systemctl status exo-ghost
tail -f data/service.log
```

浏览器（Mac / 手机 / 大屏，同一网络）打开：**http://exo.local:8000**

发命令：

```bash
uv run python -m tools.ctl status
uv run python -m tools.ctl policy resist --gain 0.5
uv run python -m tools.ctl zero
uv run python -m tools.ctl estop
```

## 六、常见问题

| 症状 | 原因 / 解法 |
|---|---|
| `Permission denied: /dev/ttyUSB0` | dialout 组没生效 → 重新登录或重启 |
| 找不到串口 | 外骨骼没开机 / 数据线只能充电不能传数据 / 换个 USB 口 |
| `exo.local` 连不上 | 换 IP 直连；或 `sudo apt install avahi-daemon` |
| 板子莫名重启、WiFi 断 | **供电不足**：换短而粗的线、充电宝要 5V 2A 以上 |
| 数据流 < 150 Hz | 先看外骨骼电量；再看 `dmesg | tail` 有没有 USB 报错 |

## 七、网络怎么摆

Mac 要同时**上网**（Agent 调模型）和**连板子**（看曲线），别让两件事抢同一块网卡：

- **A**：两台都连会场 WiFi（最简单，先试这个；若会场开了客户端隔离就不通）
- **B**：Mac 插有线上网 + WiFi 连板子热点（最稳，macOS 自动按服务顺序走有线）
- **C**：Mac 走 iPhone 蓝牙个人热点上网 + WiFi 连板子（会场网崩了的备胎）
