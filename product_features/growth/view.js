export async function mount(root, {api, ui}) {
  ui.heading(root, '和自己，一起往前走。', '每一枚徽章，都来自你留下的运动记录。');
  const data = await api('/api/growth/progress'), stats = ui.el('div', null, 'grid stats');
  stats.append(ui.metric('有效运动', data.sessions, '次'), ui.metric('留下记录', data.days, '天'), ui.metric('累计活动', data.movement_minutes, '分钟'));
  root.append(stats);
  if (!data.sessions) root.append(ui.el('p', '完成并收录一次穿戴运动后，就会开始积累成长。桌面调试和未完成记录不计入。', 'inline-note'));
  const cards = ui.el('div', null, 'grid');
  for (const b of data.badges) {
    const card = ui.card(); if (!b.unlocked) card.classList.add('locked');
    card.append(ui.el('div', b.icon, 'badge-icon'), ui.el('h2', b.title), ui.el('p', b.description, 'muted'));
    const bar = ui.el('div', null, 'progress'), fill = ui.el('span');
    fill.style.width = `${Math.min(100, b.value / b.target * 100)}%`; bar.append(fill);
    card.append(bar, ui.el('p', b.unlocked ? '已解锁' : `${b.value} / ${b.target}`, 'accent')); cards.append(card);
  }
  root.append(cards, ui.el('p', '左右幅度比只描述这次记录的运动特征，不用于判断康复效果。', 'muted'));
}
