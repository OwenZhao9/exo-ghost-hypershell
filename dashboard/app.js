// Exo Ghost 监视器：连 WebSocket、画曲线、发命令。
// 页面结构在 index.html，配色在 style.css，这里只放行为。
"use strict";
(() => {
'use strict';
const $ = id => document.getElementById(id);
const host = location.hostname || 'localhost';
const WS = `ws://${host}:8765`;
$('addr').textContent = `手机：http://${host}:8000`;

// ---------- 数据缓冲（保留 120 秒，可回看） ----------
const KEEP = 120;
const T = [], V = [];                    // V[i] = 18 个字段的数组
const EVENTS = [];                       // {t, msg, level}
let status = null, paused = false, win = 10, showImu = false;
let cursor = null, cursorAt = 0;         // 十字准星时间（悬停/暂停时）；cursorAt = 最后一次移动的时刻

// 字段索引
const F = {ldeg:0, rdeg:1, ldps:2, rdps:3, tl:4, tr:5, scale:6, pitch:7, roll:8, yaw:9, gx:10, gy:11, gz:12, ax:13, ay:14, az:15, kpa:16};
const C = {blue:'#5aa9ff', pink:'#ff7ab6', green:'#3ddc84', amber:'#ffb454', cyan:'#4fd1d9', violet:'#b28dff'};

// 派生量
function val(v, key){
  if (key === 'acc')  return Math.hypot(v[F.ax], v[F.ay], v[F.az]);
  if (key === 'gyro') return Math.hypot(v[F.gx], v[F.gy], v[F.gz]);
  return v[F[key]];
}

// ---------- 图表定义：固定量程 + 可切自动 ----------
const CHARTS = [
  {id:'ang',   title:'髋关节角度',   unit:'°',    small:false, imu:false,
   fixed:[-120,120], ladder:[15,30,60,120],
   series:[{k:'ldeg', n:'左', c:C.blue}, {k:'rdeg', n:'右', c:C.pink}]},
  {id:'vel',   title:'髋关节角速度', unit:'°/s',  small:false, imu:false,
   fixed:[-300,300], ladder:[30,75,150,300],
   series:[{k:'ldps', n:'左', c:C.blue}, {k:'rdps', n:'右', c:C.pink}]},
  {id:'tau',   title:'下发力矩',     unit:'Nm',   small:false, imu:false,
   fixed:[-2,2], ladder:[0.25,0.5,1,2], limit:1.5,
   series:[{k:'tl', n:'τ左', c:C.blue}, {k:'tr', n:'τ右', c:C.pink}]},
  {id:'att',   title:'腰部姿态',     unit:'°',    small:true,  imu:true,
   fixed:[-180,180], ladder:[45,90,180],
   series:[{k:'pitch', n:'前后倾', c:C.cyan}, {k:'roll', n:'左右倾', c:C.violet}]},
  {id:'imu',   title:'腰部加速度 / 陀螺',  unit:'g · °/s',  small:true, imu:true,
   fixed:[0,4], ladder:[2,4], positive:true,
   series:[{k:'acc', n:'|a| g', c:C.green}, {k:'gyro', n:'|ω|/100', c:C.amber, div:100}]},
];
const fixedMode = {};   // true = 锁定最大量程；false = 自适应挡位（默认）
const curStep = {};     // 当前挡位（半量程）
const smallOK = {};     // 更小挡位已经够用的起始时刻（用于延迟缩小）

const host_el = $('charts');
for (const ch of CHARTS){
  const d = document.createElement('div');
  d.className = 'chart' + (ch.small ? ' sm' : '');
  d.id = 'c_' + ch.id;
  d.innerHTML = `<div class="chead"><span class="t">${ch.title}</span><span class="leg" id="lg_${ch.id}"></span>
    <span class="sc"><button data-a="1" class="on">自适应</button><button data-a="0">固定</button></span></div>
    <div class="cwrap"><canvas id="cv_${ch.id}"></canvas></div>`;
  host_el.appendChild(d);
  fixedMode[ch.id] = false; curStep[ch.id] = ch.ladder[ch.ladder.length-1]; smallOK[ch.id] = 0;
  d.querySelectorAll('.sc button').forEach(b => b.onclick = () => {
    fixedMode[ch.id] = b.dataset.a === '0';
    d.querySelectorAll('.sc button').forEach(x => x.classList.toggle('on', x === b));
  });
  if (ch.imu) d.style.display = 'none';
}

// ---------- 绘制 ----------
function fmt(v, dp){ const a = Math.abs(v); return v.toFixed(dp !== undefined ? dp : (a >= 100 ? 0 : a >= 10 ? 1 : 2)); }

function draw(){
  if (cursor !== null && !paused && performance.now() - cursorAt > 1500) cursor = null;   // 停住不动就回到最新值
  const t1 = T.length ? T[T.length-1] : 0, t0 = t1 - win;
  for (const ch of CHARTS){
    if (ch.imu && !showImu) continue;
    const cv = $('cv_' + ch.id); if (!cv) continue;
    const dpr = window.devicePixelRatio || 1, r = cv.getBoundingClientRect();
    if (r.width < 2) continue;
    if (cv.width !== (r.width*dpr|0) || cv.height !== (r.height*dpr|0)){ cv.width = r.width*dpr|0; cv.height = r.height*dpr|0; }
    const g = cv.getContext('2d'); g.setTransform(dpr,0,0,dpr,0,0);
    const w = r.width, h = r.height, pl = 46, pr = 8, pt = 6, pb = 15, pw = w-pl-pr, ph = h-pt-pb;
    g.clearRect(0,0,w,h);

    // 可见区间
    let i0 = 0; while (i0 < T.length && T[i0] < t0) i0++;

    // 量程：示波器式阶梯挡位，超了立刻放大，变小了等 3 秒再缩
    let lo, hi;
    const lad = ch.ladder, top = lad[lad.length-1];
    if (fixedMode[ch.id]){ curStep[ch.id] = top; }
    else {
      let mx = 0;
      for (const s of ch.series) for (let k=i0;k<T.length;k++){ const y = Math.abs(val(V[k], s.k)/(s.div||1)); if (y>mx) mx = y; }
      const need = lad.find(v => v >= mx*1.08) || top;
      const now = performance.now();
      if (need > curStep[ch.id]) { curStep[ch.id] = need; smallOK[ch.id] = 0; }          // 放大：立刻
      else if (need < curStep[ch.id]) {                                                  // 缩小：延迟 3 秒
        if (!smallOK[ch.id]) smallOK[ch.id] = now;
        else if (now - smallOK[ch.id] > 3000) { curStep[ch.id] = need; smallOK[ch.id] = 0; }
      } else smallOK[ch.id] = 0;
    }
    const st = curStep[ch.id];
    if (ch.positive){ lo = 0; hi = st; } else { lo = -st; hi = st; }
    const ticks = ch.positive ? [0, st/2, st] : [-st, -st/2, 0, st/2, st];

    const Y = v => pt + ph*((hi-v)/(hi-lo));
    const X = t => pl + pw*(1-(t1-t)/win);

    // 网格 + Y 轴刻度
    g.font = '11px ui-monospace,Menlo,monospace'; g.textAlign='right'; g.lineWidth = 1;
    for (const tk of ticks){
      const y = Y(tk); if (y < pt-1 || y > pt+ph+1) continue;
      g.strokeStyle = Math.abs(tk) < 1e-9 ? '#39404f' : 'var(--grid)';
      g.strokeStyle = Math.abs(tk) < 1e-9 ? '#3a4252' : '#1e222b';
      g.beginPath(); g.moveTo(pl,y); g.lineTo(w-pr,y); g.stroke();
      const dp = st >= 100 ? 0 : st >= 10 ? 0 : st >= 1 ? 1 : 2;
      g.fillStyle = '#7b8496'; g.fillText(tk.toFixed(dp), pl-5, y+4);
    }
    // 时间刻度
    g.textAlign='center';
    const step = win <= 5 ? 1 : win <= 10 ? 2 : win <= 30 ? 5 : 10;
    for (let s=0;s<=win;s+=step){
      const x = pl+pw*(1-s/win);
      g.strokeStyle='#1a1e26'; g.beginPath(); g.moveTo(x,pt); g.lineTo(x,pt+ph); g.stroke();
      g.fillStyle='#69707f'; g.fillText(s===0?'现在':`-${s}s`, x, h-3);
    }
    // 力矩上限参考线
    if (ch.limit && ch.limit <= hi){
      g.strokeStyle = '#ff5d5d55'; g.setLineDash([5,4]); g.lineWidth = 1;
      for (const v of [ch.limit, -ch.limit]){ const y = Y(v); g.beginPath(); g.moveTo(pl,y); g.lineTo(w-pr,y); g.stroke(); }
      g.setLineDash([]);
    }
    // 事件竖线
    for (const ev of EVENTS){
      if (ev.t < t0 || ev.t > t1) continue;
      const x = X(ev.t);
      g.strokeStyle = ev.level==='err' ? '#ff5d5d66' : ev.level==='warn' ? '#ffb45466' : '#5aa9ff44';
      g.setLineDash([3,3]); g.beginPath(); g.moveTo(x,pt); g.lineTo(x,pt+ph); g.stroke(); g.setLineDash([]);
    }
    // 曲线
    const legend = [];
    for (const s of ch.series){
      g.strokeStyle = s.c; g.lineWidth = 1.8; g.beginPath();
      let started = false;
      for (let k=i0;k<T.length;k++){
        const x = X(T[k]), y = Y(val(V[k], s.k)/(s.div||1));
        if (!started){ g.moveTo(x,y); started = true; } else g.lineTo(x,y);
      }
      g.stroke();
      // 图例读数：准星处或最新值
      let idx = T.length-1;
      if (cursor !== null){ idx = nearest(cursor); }
      const cur = idx >= 0 && V[idx] ? val(V[idx], s.k)/(s.div||1) : null;
      legend.push(`<span><i style="background:${s.c}"></i>${s.n} <b>${cur===null?'—':fmt(cur)}</b></span>`);
    }
    $('lg_'+ch.id).innerHTML = legend.join('') + `<span style="color:#69707f">${ch.unit}</span>`;

    // 准星
    if (cursor !== null && cursor >= t0 && cursor <= t1){
      const x = X(cursor);
      g.strokeStyle = '#ffffff55'; g.lineWidth = 1; g.beginPath(); g.moveTo(x,pt); g.lineTo(x,pt+ph); g.stroke();
    }
  }
  requestAnimationFrame(draw);
}
function nearest(t){
  let lo=0, hi=T.length-1;
  while (lo<hi){ const m=(lo+hi)>>1; if (T[m]<t) lo=m+1; else hi=m; }
  return lo;
}
requestAnimationFrame(draw);

// 准星交互：在任意图上移动/触摸
host_el.addEventListener('pointermove', e => {
  const cv = e.target.closest('canvas'); if (!cv || !T.length) { return; }
  const r = cv.getBoundingClientRect(), pl=46, pr=8, pw=r.width-pl-pr;
  const f = (e.clientX - r.left - pl)/pw;
  const t1 = T[T.length-1];
  cursor = t1 - win*(1-Math.max(0,Math.min(1,f)));
  cursorAt = performance.now();
});
host_el.addEventListener('pointerleave', () => { if (!paused) cursor = null; });

// ---------- WebSocket ----------
let ws;
function connect(){
  ws = new WebSocket(WS);
  ws.onopen = () => { $('conn').textContent='已连接'; $('dot').classList.add('on'); };
  ws.onclose = () => { $('conn').textContent='断开，重连中…'; $('dot').classList.remove('on'); setState('OFFLINE'); T.length=0; V.length=0; setTimeout(connect, 1000); };
  ws.onerror = () => ws.close();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.k === 's'){
      if (paused) return;
      if (T.length && m.t - T[T.length-1] > 0.3){ T.length=0; V.length=0; cursor=null; }
      T.push(m.t); V.push(m.v);
      while (T.length && T[0] < m.t - KEEP){ T.shift(); V.shift(); }
      while (EVENTS.length && EVENTS[0].t < m.t - KEEP) EVENTS.shift();
      $('vL').textContent = m.v[F.ldeg].toFixed(1)+'°';
      $('vR').textContent = m.v[F.rdeg].toFixed(1)+'°';
      $('vT').textContent = `${m.v[F.tl]>=0?'+':''}${m.v[F.tl].toFixed(2)} / ${m.v[F.tr]>=0?'+':''}${m.v[F.tr].toFixed(2)}`;
    } else if (m.k === 'st'){
      if (m.state === 'RECONN' && status?.state !== 'RECONN') {
        T.length=0; V.length=0; cursor=null;
        $('vL').textContent='—'; $('vR').textContent='—'; $('vT').textContent='—';
      }
      status = m; setState(m.state);
      $('vP').textContent = {zero:'松劲', resist:'阻尼', assist:'助力', hold:'位置保持', torque:'恒定力矩'}[m.policy] || m.policy;
      $('vHz').textContent = m.hz.toFixed(0)+' Hz';
      $('vW').textContent = (m.work_J>=0?'+':'')+m.work_J.toFixed(1);
      $('arm').style.display = m.state==='TRIPPED' ? '' : 'none';
      document.querySelectorAll('[data-p]').forEach(b => b.classList.toggle('on', b.dataset.p===m.policy));
      Ghost.update(m);
    } else if (m.k === 'ev'){
      EVENTS.push({t:m.t, msg:m.msg, level:m.level||'info'});
      const d = document.createElement('div'); d.className = m.level||'info';
      d.textContent = `[${new Date(m.t*1000).toTimeString().slice(0,8)}] ${m.msg}`;
      $('log').prepend(d); while ($('log').children.length > 60) $('log').removeChild($('log').lastChild);
    }
  };
}
function setState(s){
  const el = $('state'); el.className = 'badge '+s;
  el.textContent = {ARMED:'运行中', TRIPPED:'急停锁存', LEGS_OFF:'腿板掉线', RECONN:'重连中', QUIET:'安全等待', OFFLINE:'未连接'}[s] || s;
}
connect();
const send = o => { if (ws && ws.readyState===1) ws.send(JSON.stringify(o)); };

// ---------- 控件 ----------
$('win').querySelectorAll('button').forEach(b => b.onclick = () => {
  win = +b.dataset.w; $('win').querySelectorAll('button').forEach(x=>x.classList.toggle('on', x===b));
});
$('pause').onclick = () => {
  paused = !paused; $('pause').classList.toggle('on', paused);
  $('pause').textContent = paused ? '▶ 继续' : '⏸ 暂停';
  if (!paused) cursor = null;
};
$('imu').onclick = () => {
  showImu = !showImu; $('imu').classList.toggle('on', showImu);
  CHARTS.filter(c=>c.imu).forEach(c => $('c_'+c.id).style.display = showImu ? '' : 'none');
};
let sel = 'resist';
document.querySelectorAll('[data-p]').forEach(b => b.onclick = () => {
  sel = b.dataset.p; document.querySelectorAll('[data-p]').forEach(x=>x.classList.toggle('on', x===b));
});
$('sg').oninput = () => $('sgv').textContent = (+$('sg').value).toFixed(2);
$('sm').oninput = () => $('smv').textContent = (+$('sm').value).toFixed(1)+' Nm';
$('apply').onclick = () => send({op:'policy', policy:sel, gain:+$('sg').value, max:+$('sm').value});
$('estop').onclick = () => send({op:'estop'});
$('arm').onclick = () => { if (confirm('确认现场安全，重新武装？（回到松劲）')) send({op:'arm'}); };
document.addEventListener('keydown', e => { if (e.key===' '){ e.preventDefault(); $('pause').click(); } });
})();
