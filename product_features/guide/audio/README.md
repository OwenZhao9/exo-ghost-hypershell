# 眼镜 Demo 语音提示

本目录只存放四条固定中文 WAV 提示，由用户要求合成并用于本机电脑播放：

| 文件 | 合成文字 | 触发 |
| --- | --- | --- |
| `left.wav` | 演示提示，向左。 | EvoMap 判断画面左侧较空 |
| `right.wav` | 演示提示，向右。 | EvoMap 判断画面右侧较空 |
| `unknown.wav` | 演示提示，无法判断。 | 方向不明确；也用于手动试听 |
| `stop.wav` | 演示已经停止。 | 手动停止或本轮自然结束 |

使用 [Kokoro 82M v1.1 中文模型](https://huggingface.co/hexgrad/Kokoro-82M-v1.1-zh)的 `zf_001` 声线离线生成。模型许可为 Apache 2.0；[kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) 运行库为 MIT 许可。生成时未调用设备、浏览器或操作系统的语音合成。模型权重与临时工具保留在本机缓存，不纳入 Git。

2026-09-23 用 Whisper Base 中文识别复核四条语音的关键词与方向对应；四个文件均为单声道 24 kHz PCM WAV，时长约 2–2.5 秒。合成音仅用于有人看护的桌面演示，不代表可靠导盲指令。
