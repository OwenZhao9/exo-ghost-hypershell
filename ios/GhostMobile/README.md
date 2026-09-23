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
- 先停止旧版控制进程，再从**本分支**启动真机服务；不可让两个进程同时占用外骨骼串口。启动后在 Mac 本机运行 `python -m tools.mobile_pairing --state-dir data --ws-port 8765`，将显示的 Mac 地址和配对口令输入 iPhone。口令只保存在忽略提交的 `data/mobile-pairing-token`，权限 0600；App 保存到本机 Keychain。
- 对于不同端口或 `--state-dir`，配对命令参数须与服务完全一致。Mac 和 iPhone 必须在同一可信局域网内。App 只接受局域网 IPv4 地址，测试版未使用公网转发或远程云控。
- 同一台 Mac 上旧网页仍可本机操作；局域网客户端必须先用口令配对，配对后仅能请求低增益助力、阻尼、松劲、急停及心跳。手机端无重新武装、位置保持和直接力矩入口。

## 安全边界

- 后端仅在**真机**、已武装、串口就绪、腿板在线、数据率至少 50 Hz 且不处于 15 秒安全等待期时接受手机策略。助力 `gain ≤ 0.2`、`max ≤ 0.8 Nm`；阻尼 `gain ≤ 0.3`、`max ≤ 1.5 Nm`。控制仍经原有斜坡、限幅和急停链路。
- 手机持续发送心跳，控制租约两秒到期。断线、App 后台、心跳超时、腿板状态变化或串口断流会结束手机租约并回到 `zero`；重新连接后需要用户再次选择动作。
- 手机只显示收到的实时角度帧；断线清空曲线。真机固件可能有基础力矩和上电自检动作，上位机 `zero` 并非物理零力矩承诺。
- WebSocket 使用可信局域网内的明文 `ws://` 与随机口令，**不适合不可信 Wi-Fi、跨网访问或公网暴露**。正式远程使用须另做加密传输和部署审查。

## TestFlight 状态

本项目已在本机用 Xcode 26.4 编译 iOS 16 最低目标，并成功导出 App Store Connect 发行签名的 `build/export/GhostMobile.ipa`。App Store Connect 已创建 `Ghost 外骨骼`（Bundle ID `com.owenzhao.exoghost.mobile`），TestFlight 构建 `1.0 (1)` 于 2026-09-23 上传并处理完成。出口合规问题已根据 App 仅调用 Apple 系统加密能力的实现填写。手动分发的内部群组 `Ghost iPhone 内测` 已分配此构建，账户持有人已受邀；邀请仍需在 iPhone 的 TestFlight 中接受。真机 iPhone 8 的系统版本、安装、配对、控制和失联保护仍须现场验证。
