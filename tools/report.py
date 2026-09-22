"""生成会话交付单：

    uv run python -m tools.report                      # 用最近一次会话
    uv run python -m tools.report data/sim_xxx.csv     # 指定某一次
    uv run python -m tools.report --open               # 生成后用浏览器打开

写出来的是本地 HTML 文件，不上传、不发布到任何地方。
"""
from __future__ import annotations

import argparse
import csv
import glob
import os
import time

from report.collect import collect
from report.render import render
from runtime.journal import read_journal


def latest_csv(log_dir: str = "data") -> str | None:
    files = [f for f in glob.glob(os.path.join(log_dir, "*.csv"))
             if os.path.basename(f)[0] not in "."]
    return max(files, key=os.path.getmtime) if files else None


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="把一次会话变成一份 HTML 交付单")
    ap.add_argument("csv", nargs="?", default=None, help="会话 CSV；不给就用 data/ 下最新的")
    ap.add_argument("-o", "--out", default=None, help="输出路径，默认与 CSV 同名的 .html")
    ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
    a = ap.parse_args(argv)

    path = a.csv or latest_csv()
    if not path or not os.path.exists(path):
        raise SystemExit("找不到会话 CSV。先跑一次 runtime.service，或直接给出路径。")
    stem = os.path.splitext(path)[0]
    journal_path = stem + ".jsonl"
    out = a.out or stem + ".html"

    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    records = read_journal(journal_path)
    if not records:
        print(f"注意：没有找到流水 {journal_path}，交付单里只会有传感器那部分。")

    data = collect(records, rows)
    html = render(data, csv_path=path, journal_path=journal_path,
                  generated_at=time.time())
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    s = data["stream"]
    print(f"交付单：{out}")
    print(f"  {s.get('n', 0)} 帧 / {s.get('span_s', 0):.0f} s，"
          f"事件 {len(data['events'])} 条，判断 {data['decision_stats']['n']} 次，"
          f"归因 {len(data['problems'])} 条")
    if a.open:
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(out))


if __name__ == "__main__":
    main()
