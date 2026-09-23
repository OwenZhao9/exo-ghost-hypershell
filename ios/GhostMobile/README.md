# Ghost iPhone 控制端

独立分支 `feat/ios-mobile-GPT`。SwiftUI 原生应用，最低 iOS 16，iPhone 8 可安装。项目从 `project.yml` 生成：

```sh
xcodegen generate --spec ios/GhostMobile/project.yml
xcodebuild -project ios/GhostMobile/GhostMobile.xcodeproj -scheme GhostMobile \
  -configuration Release -sdk iphoneos -destination 'generic/platform=iOS' \
  CODE_SIGNING_ALLOWED=NO build
```

## 连接方式

- Mac 上的控制服务独占 USB 串口，手机通过同一局域网连接 Mac 的 WebSocket，不能直接把设备 USB 串口接到 iPhone。
- 真机连接时先停止旧版控制进程，再从**本分支**启动服务；不可让两个进程同时占用外骨骼串口。Mac 的口令保存在忽略提交的 `data/mobile-pairing-token`，权限 0600；`1.0 (3)` 在打包时读取它，App 首次运行后保存到 iPhone Keychain，无需现场输入。
- 对于不同端口或 `--state-dir`，配对命令参数须与服务完全一致。Mac 和 iPhone 必须在同一可信局域网内。App 只接受局域网 IPv4 地址，测试版未使用公网转发或远程云控。
- `1.0 (3)` 的现场版无需扫码或手输。先运行 `python -m tools.prepare_mobile_demo --state-dir data --ws-port 8765`，然后在 `xcodebuild archive` 中加入 `-xcconfig ios/GhostMobile/DemoPairing.local.xcconfig`。脚本生成的本机配置文件权限为 0600、被 Git 忽略；Xcode 将地址和口令写入该次 IPA 的 Info.plist，App 首次运行后保存到本机设置和 Keychain，并自动尝试连接。IPA 中的口令可被提取，所以只能发给获授权的内测人员。Mac 更换 Wi-Fi 或 IP 时，重新构建，或在 App 的“连接设置”中更改地址。`1.0 (2)` 的扫码版仍作为历史构建保留。
- 同一台 Mac 上旧网页仍可本机操作；局域网客户端必须先用口令配对，配对后仅能请求低增益助力、阻尼、松劲、急停及心跳。手机端无重新武装、位置保持和直接力矩入口。

## 安全边界

- 后端仅在**真机**、已武装、串口就绪、腿板在线、数据率至少 50 Hz 且不处于 15 秒安全等待期时接受手机策略。助力 `gain ≤ 0.2`、`max ≤ 0.8 Nm`；阻尼 `gain ≤ 0.3`、`max ≤ 1.5 Nm`。控制仍经原有斜坡、限幅和急停链路。
- 手机持续发送心跳，控制租约两秒到期。断线、App 后台、心跳超时、腿板状态变化或串口断流会结束手机租约并回到 `zero`；重新连接后需要用户再次选择动作。
- 手机只显示收到的实时角度帧；断线清空曲线。真机固件可能有基础力矩和上电自检动作，上位机 `zero` 并非物理零力矩承诺。
- WebSocket 使用可信局域网内的明文 `ws://` 与随机口令，**不适合不可信 Wi-Fi、跨网访问或公网暴露**。正式远程使用须另做加密传输和部署审查。

## TestFlight 状态

本项目已在本机用 Xcode 26.4 编译 iOS 16 最低目标，并成功导出 App Store Connect 发行签名的安装包。App Store Connect 已创建 `Ghost 外骨骼`（Bundle ID `com.owenzhao.exoghost.mobile`）；`1.0 (1)`、扫码版 `1.0 (2)` 和预置连接版 `1.0 (3)` 均已处理，并分配给手动分发的内部群组 `Ghost iPhone 内测`（1 名测试员）。App Store Connect 显示 `1.0 (3)` 已在一台 iPhone 8 Plus 上安装。模拟器确认预置地址、启动后自动连接尝试、离线时控制按钮禁用；手机上的真实连接、控制和失联保护仍须现场验证。
