export async function mount(root, {api, config, device, ui}) {
  ui.heading(root, '今天，想怎样动起来？', '选择适合这次运动的模式。设备就绪后，手动开始。');
  const {presets} = await api('/api/modes/presets');
  const message = ui.el('p', '', 'inline-note'); root.append(message);
  const grid = ui.el('div', null, 'grid mode-grid'), controls = [];
  for (const [index, p] of presets.entries()) {
    const card = ui.card(p.title), level = ui.el('select');
    card.classList.add('mode-card');
    card.prepend(ui.el('span', `${String(index + 1).padStart(2, '0')} / ${p.id.toUpperCase()}`, 'mode-index'));
    for (let i = 0; i < p.levels.length; i++) { const l = p.levels[i]; const o = ui.el('option', `${l.name} · 上限 ${l.max} Nm`); o.value = i; level.append(o); }
    const start = ui.button(`开始${p.id === 'assist' ? '助力' : '锻炼'}`, () => {
      const chosen = p.levels[Number(level.value)]; device.send({op: 'policy', policy: p.id, gain: chosen.gain, max: chosen.max});
      ui.notify('已发送请求，请以设备当前模式为准');
    }, 'button primary'); controls.push(start);
    card.append(ui.el('p', p.description, 'muted'), ui.field('强度', level), start); grid.append(card);
  }
  root.append(grid);
  const actions = ui.el('div', null, 'row mode-actions'), zero = ui.button('松劲', () => device.send({op: 'zero'})),
    stop = ui.button('急停', () => device.send({op: 'estop'}), 'button danger');
  actions.append(zero, stop); root.append(actions);
  const live = ui.card('当前运动'), state = ui.el('p', '等待设备数据', 'muted');
  live.classList.add('live-panel'); live.append(state);
  const plots = [];
  for (const [title, indices, unit, range] of [['髋关节角度', [0, 1], '°', 120], ['下发力矩', [4, 5], 'Nm', 2]]) {
    const c = ui.el('canvas'); c.setAttribute('aria-label', `${title}实时曲线：左腿绿色，右腿橙色`);
    const plot = ui.el('div', null, 'plot');
    plot.append(ui.el('h3', `${title} · ${unit}`), c); live.append(plot); plots.push({c, indices, range});
  }
  root.append(live);
  const update = () => {
    for (const b of controls) b.disabled = !(device.ready && config.control_enabled);
    zero.disabled = stop.disabled = !(config.control_enabled && device.ws?.readyState === WebSocket.OPEN);
    message.textContent = !device.fresh ? '等待设备连接。连接后会显示实时曲线。' :
      !config.control_enabled ? '当前可以查看运动数据。设备操作请使用控制台。' :
      device.status?.body !== 'real' ? '控制服务尚未确认真机来源，请更新控制服务后操作。' :
      !device.ready ? '设备正在等待或处于急停状态，请在控制台检查后再开始。' : '设备已就绪，可以开始运动。';
    const names = {zero: '松劲', assist: '助力', resist: '锻炼'};
    state.textContent = device.fresh ? `当前模式：${names[device.status?.policy] || device.status?.policy || '—'} · 左腿绿色 / 右腿橙色` : '等待设备数据';
  };
  let frame, lastPaint = 0, disposed = false;
  function paint(now) {
    if (disposed) return;
    if (now - lastPaint > 50) {
      lastPaint = now; const values = device.fresh ? device.history : [];
      for (const {c, indices, range} of plots) {
        const width = Math.max(c.clientWidth, 1), height = 190, scale = devicePixelRatio || 1;
        if (c.width !== Math.round(width * scale)) c.width = Math.round(width * scale);
        if (c.height !== Math.round(height * scale)) c.height = Math.round(height * scale);
        const g = c.getContext('2d'); g.setTransform(scale, 0, 0, scale, 0, 0); g.clearRect(0, 0, width, height);
        g.strokeStyle = '#35463a'; g.beginPath(); g.moveTo(0, height / 2); g.lineTo(width, height / 2); g.stroke();
        if (!values.length) { g.fillStyle = '#a5b3a5'; g.font = '14px sans-serif'; g.fillText('等待实时数据', 12, 30); continue; }
        const end = values.at(-1).t, begin = end - 10;
        indices.forEach((index, line) => {
          g.strokeStyle = ['#d5f46e', '#ffab78'][line]; g.lineWidth = 2; g.beginPath(); let previous = null;
          for (const s of values) {
            if (s.t < begin) continue;
            const x = (s.t - begin) / 10 * width, y = height / 2 - s.v[index] / range * (height / 2 - 10);
            if (previous === null || s.t - previous > .25 || s.t <= previous) g.moveTo(x, y); else g.lineTo(x, y);
            previous = s.t;
          }
          g.stroke();
        });
      }
    }
    frame = requestAnimationFrame(paint);
  }
  device.addEventListener('change', update); update(); frame = requestAnimationFrame(paint);
  return () => { disposed = true; cancelAnimationFrame(frame); device.removeEventListener('change', update); };
}
