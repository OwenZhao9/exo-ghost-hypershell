"""常驻控制服务的命令行入口。

    uv run python -m tools.service --profile table

实现已经拆到 `runtime/` 下：session / commands / events / status / service。
本文件只做转发，保持老的启动命令不变。
"""
from runtime.service import main

if __name__ == "__main__":
    main()
