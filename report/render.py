"""把 `collect()` 的结果排成一页自带样式的 HTML。

**纯函数**：进 dict 出字符串，不写文件、不碰时间、不联网，
页面里也没有任何外部资源（离线、断网、展位没 WiFi 都能打开）。
"""
from __future__ import annotations

import html
import time
from typing import Any, Mapping, Sequence

__all__ = ["render"]

POLICY_CN = {"zero": "松劲", "resist": "阻尼", "assist": "助力",
             "hold": "位置保持", "torque": "恒定力矩"}
WHO_CN = {"cli": "命令行", "web": "网页", "ghost": "Ghost 自己"}
HELD_CN = {"gate": "置信度不足", "hold": "防抖期内"}

CSS = """
:root{--bg:#0e1013;--panel:#161920;--line:#252a35;--ink:#e8eaf0;--muted:#8a93a6;
--green:#3ddc84;--red:#ff5d5d;--amber:#ffb454;--blue:#5aa9ff;--violet:#b28dff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.7 -apple-system,
"PingFang SC","Microsoft YaHei",system-ui,sans-serif;padding:28px 20px 60px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:30px 0 10px;
padding-bottom:6px;border-bottom:1px solid var(--line)}
.sub{color:var(--muted);font-size:13px;margin:0 0 24px}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:0 0 6px}
.c{background:var(--panel);border:1px solid var(--line);border-radius:9px;
padding:10px 13px;min-width:130px;flex:1}
.c .l{color:var(--muted);font-size:12px;display:block} .c .v{font-size:19px;font-weight:600;
font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:500}
td.num,td.nw{font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px}
.tag.err{background:rgba(255,93,93,.15);color:var(--red)}
.tag.warn{background:rgba(255,180,84,.15);color:var(--amber)}
.tag.ok{background:rgba(61,220,132,.15);color:var(--green)}
.tag.info{background:rgba(90,169,255,.15);color:var(--blue)}
.muted{color:var(--muted)} .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
ol.steps{margin:6px 0 0;padding-left:20px;color:var(--muted)} ol.steps li{margin:2px 0}
.bar{display:inline-block;width:70px;height:6px;border-radius:3px;background:#1e222b;
vertical-align:middle;margin-right:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--blue)}
.bar i.ok{background:var(--green)} .bar i.warn{background:var(--amber)}
.empty{color:var(--muted);font-style:normal;padding:10px 0}
footer{color:var(--muted);font-size:12px;margin-top:40px;border-top:1px solid var(--line);
padding-top:12px}
"""


def e(x: Any) -> str:
    return html.escape(str(x))


def clock(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t)) if t else "—"


def card(label: str, value: Any, note: str = "") -> str:
    tail = f'<span class="l">{e(note)}</span>' if note else ""
    return f'<div class="c"><span class="l">{e(label)}</span>' \
           f'<span class="v">{e(value)}</span>{tail}</div>'


def bar(frac: float, cls: str = "") -> str:
    pct = max(0.0, min(1.0, frac)) * 100
    return f'<span class="bar"><i class="{cls}" style="width:{pct:.1f}%"></i></span>'


def _overview(d: Mapping[str, Any]) -> str:
    s, st, end = d["start"], d["stream"], d["end"]
    body = {"sim": "数字义体", "real": "真外骨骼", "auto": "自动选择"}.get(s.get("body"), s.get("body", "—"))
    cards = [
        card("身体", body, e(s.get("version", ""))),
        card("安全档", s.get("profile", "—"), f"软限幅 ±{s.get('limit','?')} Nm"),
        card("时长", f"{st.get('span_s', 0):.0f} s", f"{st.get('n', 0)} 帧"),
        card("数据率", f"{st.get('hz_mean', 0):.0f} Hz", f"最大间隔 {st.get('gap_max_ms', 0):.0f} ms"),
        card("做功", f"{st.get('work_J', 0):+.2f} J", "τ·ω·dt，跳过饱和帧"),
        card("峰值力矩", f"{st.get('tau_peak', 0):.2f} Nm"),
    ]
    if end.get("reconnects") is not None:
        cards.append(card("重连", int(end["reconnects"]), "断流自动恢复"))
    return '<div class="cards">' + "".join(cards) + "</div>"


def _ghost(d: Mapping[str, Any]) -> str:
    ds = d["decision_stats"]
    if not ds["n"]:
        return '<p class="empty">这次会话没有启用直觉层（--no-decide）。</p>'
    wants = "、".join(f"{POLICY_CN.get(k, k)} {v} 次" for k, v in ds["wants"].items())
    cards = [
        card("判断次数", ds["n"], wants),
        card("没有采纳", ds["held"], "不确定就不动"),
        card("自动下发", ds["applied"], "autopilot 开时才会有"),
        card("置信度", f"{ds['conf_mean']:.2f}" if ds["conf_mean"] is not None else "—",
             f"最低 {ds['conf_min']} / 最高 {ds['conf_max']}" if ds["conf_mean"] is not None else ""),
    ]
    rows = []
    prev = None
    for x in d["decisions"]:
        key = (x.get("want"), x.get("applied"), x.get("held_by"))
        if key == prev:          # 连续相同的判断只留第一条，免得几百行全一样
            continue
        prev = key
        verdict = (f'<span class="tag warn">{HELD_CN.get(x.get("held_by"), "未采纳")}</span> '
                   f'保持 {POLICY_CN.get(x.get("applied"), x.get("applied"))}' if x.get("held")
                   else (f'<span class="tag ok">已下发</span> {POLICY_CN.get(x.get("applied"))}'
                         if x.get("autopilot")
                         else f'维持 {POLICY_CN.get(x.get("applied"), x.get("applied"))}'))
        conf = float(x.get("confidence", 0))
        rows.append(
            f'<tr><td class="num">{clock(x.get("t", 0))}</td>'
            f'<td class="nw">{e(POLICY_CN.get(x.get("want"), x.get("want")))}</td>'
            f'<td class="num">{bar(conf, "ok" if conf >= 0.55 else "warn")}{conf:.2f}</td>'
            f'<td>{verdict}</td><td class="muted">{e(x.get("why", ""))}</td></tr>')
    table = ("<table><tr><th>时刻</th><th>想选</th><th>置信度</th><th>结果</th><th>依据</th></tr>"
             + "".join(rows) + "</table>") if rows else '<p class="empty">没有判断记录。</p>'
    return ('<div class="cards">' + "".join(cards) + "</div>"
            + '<p class="muted" style="margin:10px 0 6px">'
              '连续重复的判断已合并，只列状态变化的那几次。</p>' + table)


FAULT_CN = {"legs_offline": "腿板掉线", "port_lost": "串口断开", "tilt": "被扳倒"}


def _events(d: Mapping[str, Any]) -> str:
    inj = d.get("injected") or []
    head = ('<p class="muted">本次会话有 <b>%d</b> 次<b>人为注入</b>的故障（%s）——'
            '它们是演示的一部分，不是设备自己出的问题。'
            '其余事件才是真实发生的。</p>'
            % (len(inj), "、".join(FAULT_CN.get(i["kind"], i["kind"]) for i in inj))) if inj else ""
    head += ('<p class="muted">回忆是按信号在经验库里找<b>相似的过往记录</b>，'
             '不是诊断。相似度低的时候要自己判断它适不适用。</p>')
    if not d["events"]:
        return head + '<p class="empty">这次会话没有设备异常。</p>'
    out = []
    for h in d["events"]:
        r = h.get("recall")
        block = ""
        if r and r.get("hits"):
            top = r["hits"][0]
            steps = "".join(f"<li>{e(s)}</li>" for s in top.get("steps", []))
            block = (f'<div style="margin-top:6px">查到经验 <b>{e(top["title"])}</b>'
                     f' <span class="muted">相似度 {top["score"]:.2f}</span>'
                     f'<ol class="steps">{steps}</ol></div>')
        elif r:
            block = (f'<div class="muted" style="margin-top:6px">回忆「{e(r["query"])}」没有命中'
                     f'（{r.get("weak", 0)} 条沾边但相似度不够）</div>')
        out.append(f'<tr><td class="num">{clock(h["t"])}</td>'
                   f'<td><span class="tag {e(h["level"])}">{e(h["event"] or "事件")}</span></td>'
                   f'<td>{e(h["msg"])}{block}</td></tr>')
    return head + "<table><tr><th>时刻</th><th>事件</th><th>发生了什么 / Ghost 怎么处置</th></tr>" \
           + "".join(out) + "</table>"


def _problems(d: Mapping[str, Any]) -> str:
    if not d["problems"]:
        return '<p class="empty">这次会话没有需要归因的问题。</p>'
    rows = "".join(f'<tr><td>{e(p["what"])}</td><td class="muted">{e(p["why"])}</td>'
                   f'<td class="muted">{e(p["evidence"])}</td></tr>' for p in d["problems"])
    return "<table><tr><th>什么没成</th><th>为什么</th><th>证据 / 说明</th></tr>" + rows + "</table>"


def _commands(d: Mapping[str, Any]) -> str:
    c = d["commands"]
    if not c["n"]:
        return '<p class="empty">这次会话没有下发命令。</p>'
    by = "、".join(f"{WHO_CN.get(k, k)} {v} 条" for k, v in c["by"].items())
    return ('<div class="cards">' + card("命令总数", c["n"], by)
            + card("策略切换", c["policy_switches"]) + "</div>")


def _stream(d: Mapping[str, Any]) -> str:
    s = d["stream"]
    if not s.get("n"):
        return f'<p class="empty">{e(s.get("note", "没有传感器数据"))}</p>'
    rows = [
        ("左髋角度范围", f'{s["ldeg_range"][0]} … {s["ldeg_range"][1]} °'),
        ("右髋角度范围", f'{s["rdeg_range"][0]} … {s["rdeg_range"][1]} °'),
        ("关节角速度峰值", f'{s["dps_peak"]} °/s（已排除饱和帧）'),
        ("饱和帧数", f'{s["saturated_frames"]} / {s["n"] * 2} 个读数'),
        ("峰值下发力矩", f'{s["tau_peak"]} Nm'),
        ("累计做功", f'{s["work_J"]:+.3f} J'),
    ]
    return "<table>" + "".join(f'<tr><th>{e(k)}</th><td class="num">{e(v)}</td></tr>'
                               for k, v in rows) + "</table>"


def render(d: Mapping[str, Any], *, title: str = "exo-ghost 会话交付单",
           csv_path: str = "", journal_path: str = "", generated_at: float = 0.0) -> str:
    """把汇总结果排成一页 HTML。`generated_at` 由调用方给，保证同样输入渲染结果一样。"""
    start_t = d["start"].get("t", 0)
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_t)) if start_t else "时间未知"
    gen = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(generated_at)) if generated_at else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>{e(title)}</h1>
<p class="sub">会话开始于 {e(when)}　·　每条结论都来自下面两个文件，没有别的来源</p>
<h2>一、这次跑了什么</h2>{_overview(d)}
<h2>二、Ghost 判了什么，哪些没被采纳</h2>{_ghost(d)}
<h2>三、出了什么事，它自己怎么处置的</h2>{_events(d)}
<h2>四、什么没成，为什么</h2>{_problems(d)}
<h2>五、命令来自谁</h2>{_commands(d)}
<h2>六、实测包络</h2>{_stream(d)}
<footer>
原始数据：<span class="mono">{e(csv_path or "（未提供）")}</span>（每帧传感器读数）　·　
<span class="mono">{e(journal_path or "（未提供）")}</span>（事件、决策、回忆、命令的逐条流水）<br>
本页离线可看，不含任何外部资源。{'生成于 ' + e(gen) if gen else ''}
</footer></div></body></html>
"""
