export async function mount(root, {api, ui}) {
  ui.heading(root, '每一步，都留下记录。', '回看运动幅度、活动时长和左右腿的表现。');
  const [{sessions}, {files}] = await Promise.all([api('/api/sessions'), api('/api/records/sources')]);
  const add = ui.card('收录一次运动');
  if (!files.length) add.append(ui.el('p', '还没有可收录的记录。结束一次设备记录后，再打开这里。', 'muted'));
  else {
    const select = ui.el('select');
    for (const file of files) { const o = ui.el('option', file.name); o.value = file.name; select.append(o); }
    const label = ui.input(), route = ui.input();
    label.maxLength = route.maxLength = 100;
    label.placeholder = '例如：公园晨练'; route.placeholder = '例如：公园环线';
    add.append(ui.field('设备记录', select), ui.field('这次运动的名字（选填）', label), ui.field('路线（选填）', route));
    add.append(ui.button('收录记录', async () => {
      const result = await api('/api/records/import', {filename: select.value, context: {label: label.value, route: route.value}});
      ui.notify(result.added ? '记录已保存' : '这份记录已经收录过了');
      root.replaceChildren(); await mount(root, {api, ui});
    }, 'button primary'));
  }
  root.append(add);
  if (!sessions.length) { ui.empty(root, '档案还空着', '你的记录会保存在这里，刷新或重新启动后仍能查看。'); return; }
  const list = ui.el('div', null, 'list'); root.append(ui.el('h2', '历史记录'), list);
  for (const s of sessions) {
    const m = s.metrics, card = ui.card(), header = ui.el('div', null, 'record'), name = ui.el('div');
    name.append(ui.el('h3', s.context.label), ui.el('p', ui.date(s.started_at), 'muted'));
    const kind = s.eligible ? '穿戴运动' : s.body === 'sim' ? '仿真记录' : s.profile === 'table' ? '桌面记录' : '来源待确认';
    header.append(name, ui.el('span', kind, 'pill' + (s.eligible ? '' : ' muted'))); card.append(header);
    const grid = ui.el('div', null, 'grid');
    grid.append(ui.metric('有效记录时长', ui.number(m.duration_s / 60), '分钟'),
      ui.metric('左 / 右运动幅度', `${ui.number(m.left_rom_deg)} / ${ui.number(m.right_rom_deg)}`, '°'),
      ui.metric('幅度对称比', m.rom_symmetry === null ? '—' : ui.number(m.rom_symmetry * 100), '%'));
    card.append(grid);
    const details = ui.el('details'); details.append(ui.el('summary', '查看记录详情'));
    details.append(ui.el('p', `活动时长 ${ui.number(m.movement_s)} 秒 · 指令做功估计：左 ${ui.number(m.left_command_work_j)} J / 右 ${ui.number(m.right_command_work_j)} J`, 'muted'));
    details.append(ui.el('p', '指令做功反映设备下发的辅助或阻力，不代表人体肌力或节省的体力。', 'muted'));
    if (!s.complete) details.append(ui.el('p', '这份记录缺少结束标记，不计入成长统计。', 'muted'));
    if (m.gaps || m.invalid_frames) details.append(ui.el('p', `已跳过 ${m.invalid_frames} 帧无效数据、${m.gaps} 处断流间隔。`, 'muted'));
    const wrap = ui.el('div', null, 'table-wrap'), table = ui.el('table'), head = ui.el('tr');
    for (const t of ['记录分钟', '左平均角速度（°/s）', '右平均角速度（°/s）']) head.append(ui.el('th', t)); table.append(head);
    for (const w of m.speed_windows) { const tr = ui.el('tr'); for (const t of [w.minute + 1, w.left_dps, w.right_dps]) tr.append(ui.el('td', t)); table.append(tr); }
    wrap.append(table); details.append(wrap); card.append(details); list.append(card);
  }
  const personal = sessions.filter(s => s.eligible);
  if (personal.length > 1) {
    const trend = ui.card('运动变化');
    trend.append(ui.el('p', '下面按时间列出穿戴记录。路线和助力参数不同会影响结果，不据此判断肌力或康复提升。', 'muted'));
    const wrap = ui.el('div', null, 'table-wrap'), table = ui.el('table'), head = ui.el('tr');
    for (const t of ['日期', '路线', '活动分钟', '左幅度', '右幅度']) head.append(ui.el('th', t)); table.append(head);
    for (const s of personal) { const tr = ui.el('tr'); for (const t of [ui.date(s.started_at), s.context.route || '未记录', ui.number(s.metrics.movement_s / 60), ui.number(s.metrics.left_rom_deg), ui.number(s.metrics.right_rom_deg)]) tr.append(ui.el('td', t)); table.append(tr); }
    wrap.append(table); trend.append(wrap); root.append(trend);
  }
}
