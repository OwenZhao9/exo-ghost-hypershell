// Ghost 的三层状态面板：反射 / 直觉 / 经验。
// 只负责把 status 消息里的 decision、memory、tripped 画出来，不碰 WebSocket、不碰曲线。
"use strict";

const Ghost = (() => {
  const $ = id => document.getElementById(id);
  const POLICY_CN = {zero:'松劲', resist:'阻尼', assist:'助力', hold:'位置保持', torque:'恒定力矩'};
  const HELD_CN = {gate:'置信度不足，保持原策略', hold:'刚换过策略，防抖期内'};
  const cn = p => POLICY_CN[p] || p || '—';

  function bar(frac, cls){
    const pct = Math.max(0, Math.min(1, frac || 0)) * 100;
    return `<span class="gbar"><i class="${cls||''}" style="width:${pct.toFixed(1)}%"></i></span>`;
  }

  // ---------- 反射层：跑在每一帧上的硬规则 ----------
  function reflex(st){
    const el = $('gReflex');
    if (!el) return;
    if (st.tripped){
      el.innerHTML = `<div class="gline err">已急停：${st.tripped}</div>
        <div class="gnote">锁存的。确认安全后点上面的「重新武装」。</div>`;
      return;
    }
    const rx = st.reflex || {};
    const sc = (rx.scale !== undefined ? rx.scale : (st.scale === undefined ? 1 : st.scale));
    const cls = sc >= 0.99 ? 'ok' : (sc <= 0.01 ? 'warn' : '');
    let html = `<div class="gline">逐帧判定中 · 助力系数 ${sc.toFixed(2)} ${bar(sc, cls)}</div>`;
    if (sc < 0.99 && rx.binding_label){
      html += `<div class="gline warn">压着输出的是：${rx.binding_label}</div>`;
    }
    if (rx.energy_budget){
      const e = rx.energy_J_per_s || 0, b = rx.energy_budget;
      html += `<div class="grow"><span>做功</span>${bar(e / b, e > b ? 'warn' : 'ok')}
                 <b>${e.toFixed(2)} / ${b} J/s</b></div>`;
    }
    if (rx.detail){
      const chips = Object.entries(rx.detail)
        .filter(([k, v]) => v < 0.999 && k !== 'energy')   // 做功单独有一行，不重复
        .map(([k, v]) => `<span class="gchip">${(rx.labels || {})[k] || k} <b>${v.toFixed(2)}</b></span>`)
        .join('');
      if (chips) html += `<div class="gchips">${chips}</div>`;
    }
    html += '<div class="gnote">加速度 / 角速度 / 倾角 / 关节速度四路阈值，任一超限当帧清零；' +
            '助力另有转速、角度、每秒做功三道渐弱。</div>';
    el.innerHTML = html;
  }

  // ---------- 直觉层：每两秒一次的带置信度决策 ----------
  function decide(st){
    const el = $('gDecide');
    if (!el) return;
    const d = st.decision;
    if (!d){ el.innerHTML = '<div class="gnote">未启用（--no-decide）</div>'; return; }
    const last = d.last;
    if (!last){ el.innerHTML = '<div class="gnote">还没做出第一次判断…</div>'; return; }

    const pass = last.confidence >= d.min_confidence;
    const verdict = last.held
      ? `<span class="warn">${HELD_CN[last.held_by] || '未采纳'} → ${cn(last.applied)}</span>`
      : (last.autopilot ? `<span class="ok">已自动切到 ${cn(last.applied)}</span>`
                        : `维持 ${cn(last.applied)}`);
    const probs = Object.entries(last.probs)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `<div class="grow"><span>${cn(k)}</span>${bar(v, k === last.want ? 'hi' : '')}
                        <b>${(v * 100).toFixed(0)}%</b></div>`).join('');
    const feats = Object.entries(last.features || {})
      .map(([k, v]) => `<span class="gchip">${(last.labels || {})[k] || k} <b>${v}</b></span>`).join('');

    el.innerHTML = `
      <div class="gline">想选 <b>${cn(last.want)}</b> · 置信 ${last.confidence.toFixed(2)}
        ${bar(last.confidence, pass ? 'ok' : 'warn')}
        <span class="gthr">门槛 ${d.min_confidence}</span></div>
      <div class="gline">${verdict}</div>
      ${probs}
      ${last.want === 'assist' ? `<div class="gline">建议增益 <b>${last.gain.toFixed(2)}</b></div>` : ''}
      <div class="gchips">${feats}</div>
      <div class="gnote">${last.why}</div>
      <div class="gnote">后端 ${last.backend}${last.degraded ? '（本地规则，无 API key）' : ''} ·
        共判 ${d.decisions} 次，${d.held} 次因置信度不足没动 ·
        自动驾驶 ${d.autopilot ? '开' : '关'}</div>`;
  }

  // ---------- 经验层：查得到的过往教训 ----------
  function memory(st){
    const el = $('gMemory');
    if (!el) return;
    const m = st.memory;
    if (!m){ el.innerHTML = '<div class="gnote">未启用（--no-memory）</div>'; return; }
    let html = `<div class="gline">继承了 <b>${m.inherited}</b> 条经验`
             + (m.seeded ? `（本次新写入 ${m.seeded} 条）` : '') + '</div>';
    const r = m.last;
    if (r && r.hits && r.hits.length){
      const h = r.hits[0];
      html += `<div class="gline">回忆「${r.query}」→ <b>${h.title}</b>
                 <span class="gthr">相似度 ${h.score.toFixed(2)}</span></div>`;
      html += '<ol class="gsteps">' + h.steps.map(s => `<li>${s}</li>`).join('') + '</ol>';
    } else if (r){
      html += `<div class="gline warn">回忆「${r.query}」：库里没有相关经验`
            + (r.weak ? `（${r.weak} 条沾边但相似度不够）` : '') + '</div>';
    } else {
      html += '<div class="gnote">设备一出事就会自动来这里查解法。</div>';
    }
    el.innerHTML = html;
  }

  return { update(st){ reflex(st); decide(st); memory(st); } };
})();
