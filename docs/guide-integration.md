# 引路分支接入记录

用户已选择 EvoMap 官方 Gateway API，账户已有赠送额度。接口为
`https://api.evomap.ai/v1/chat/completions`，模型 ID 为
`evomap-gemini-3.1-pro-preview`。其图像透传能力仍需用获准发送的真实照片验证。

## 尚需提供的配置

- 在 EvoMap API 管理页创建 Gateway Key，并绑定 Gemini 3.1 Pro。
- 将 Key 仅保存在本机 `EVOMAP_GATEWAY_API_KEY` 环境变量中（不在聊天、源码、日志中放密钥）。

现有眼镜项目 `/Users/owenzhao/eyeGalss/luma-core` 已验证通过 BLE 拍照并保存小 JPEG
到 `/Users/owenzhao/eyeGalss/shots`。原 `examples/assistant.rs` 使用 macOS `say`，
产品不得调用该助手作为语音回退；可单独使用不含系统语音的拍照命令收图。

## 已确定的接口边界

文件所有权：`product_features/guide/` 与对应测试；通过 `register(app)` 接入产品。
与其他功能分支共用 Context、记录接口、设备只读状态；视觉请求不进入串口线程。
产品页通过 `--glasses-dir` 只读列出该目录中的 JPEG。用户主动点击单张照片后，
服务才向 EvoMap Gateway 发送图像；页面显示本机文件时间和识别结果，不把旧图当成当前环境。
失败、超时、无结果均明确显示无法识别，不据此推断道路可通行。
模型输出只用于环境描述，不直接变成外骨骼力矩命令。

## 后续验收

1. 配置 Gateway Key 后，用一张获准发送的真实照片验证 EvoMap 网关的图片输入与文字响应。
2. 验证鉴权失败、限流、超时、图片不完整与旧图的处理。
3. 连接眼镜采集流程；不调用系统语音合成。
4. 力觉引导是后续独立的真机验证项目；原方案中的力矩数值不能当作已验证安全参数。

本分支已实现手动选图、请求封装、错误提示和边界测试；尚未配置真实 Key、验证网关
图片透传或接入眼镜音频。它是照片描述试验，不是实际引路功能。
