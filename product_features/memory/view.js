export async function mount(root, {api, ui}) {
  ui.heading(root, '一个越来越了解你的 Ghost。', '保存你的目标、使用感受和习惯，让下一次运动有据可循。');
  const {profile, versions} = await api('/api/memory/profile');
  const grid = ui.el('div', null, 'grid'), info = ui.card('关于你'), params = ui.card('保存一套参数');
  const name = ui.input(profile.name), goal = ui.el('select'), notes = ui.el('textarea'); name.maxLength = 40; notes.maxLength = 2000;
  for (const [value, title] of [['hiking', '户外徒步'], ['training', '阻力锻炼'], ['both', '两者都有']]) { const o = ui.el('option', title); o.value = value; goal.append(o); }
  goal.value = profile.goal; notes.value = profile.notes;
  notes.placeholder = '例如：喜欢轻一些的助力；今天右腿的感觉……';
  info.append(ui.field('称呼', name), ui.field('运动目标', goal), ui.field('使用感受与偏好', notes));
  info.append(ui.button('保存偏好', async () => { await api('/api/memory/profile', {name: name.value, goal: goal.value, notes: notes.value}); ui.notify('偏好已保存'); }, 'button primary'));
  const mode = ui.el('select'); for (const [value, title] of [['assist', '助力'], ['resist', '锻炼']]) { const o = ui.el('option', title); o.value = value; mode.append(o); }
  const gain = ui.input('.1', 'number'), max = ui.input('.5', 'number'), note = ui.input();
  gain.min = 0; gain.max = .2; gain.step = .05; max.min = .1; max.max = .8; max.step = .1; note.maxLength = 500;
  mode.onchange = () => { gain.max = mode.value === 'assist' ? '.2' : '1'; max.max = mode.value === 'assist' ? '.8' : '1.5'; gain.value = mode.value === 'assist' ? '.1' : '.3'; max.value = '.5'; };
  params.append(ui.field('模式', mode), ui.field('增益', gain), ui.field('力矩上限（Nm）', max), ui.field('适用场景或感受', note));
  params.append(ui.el('p', '保存后会保留历史版本。设备当前参数不会因此改变。', 'muted'));
  params.append(ui.button('保存新版本', async () => {
    const result = await api('/api/memory/versions', {mode: mode.value, gain: Number(gain.value), max_torque: Number(max.value), note: note.value});
    ui.notify(result.added ? `已保存第 ${result.version} 版` : '这套参数已经保存');
    root.replaceChildren(); await mount(root, {api, ui});
  }, 'button primary'));
  grid.append(info, params); root.append(grid);
  const history = ui.card('参数成长记录');
  if (!versions.length) history.append(ui.el('p', '找到适合自己的设置后，把它保存为第一版。', 'muted'));
  for (const v of versions) {
    const item = ui.el('div', null, 'record row'), text = ui.el('div');
    text.append(ui.el('h3', `第 ${v.version} 版 · ${v.mode === 'assist' ? '助力' : '锻炼'}`), ui.el('p', `增益 ${v.gain} · 上限 ${v.max_torque} Nm · ${v.note || '未填写备注'}`, 'muted'));
    item.append(text, ui.el('span', ui.date(v.created_at), 'muted')); history.append(item);
  }
  root.append(history);
  root.append(ui.button('导出我的档案', async () => {
    const data = await api('/api/memory/export');
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
    const a = ui.el('a'); a.href = url; a.download = 'my-ghost.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }));
}
