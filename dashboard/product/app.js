import * as ui from '/ui.js';
import {Device} from '/device.js';

const config = await fetch('/api/config').then(r => r.json());
const device = new Device(config);
const root = document.querySelector('#content'), nav = document.querySelector('#navigation');
const api = async (path, payload) => {
  const response = await fetch(path, payload === undefined ? {} : {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Product-Token': config.token}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求未完成');
  return data;
};
let cleanup, revision = 0;
const home = {id: 'home', title: '总览'};
for (const feature of [home, ...config.features]) {
  const link = ui.el('a', feature.title); link.href = `#${feature.id}`; link.dataset.page = feature.id; nav.append(link);
}
async function render() {
  const current = ++revision;
  cleanup?.(); cleanup = null; root.replaceChildren();
  const id = location.hash.slice(1) || 'home';
  for (const a of nav.children) { a.classList.toggle('active', a.dataset.page === id); if (a.dataset.page === id) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); }
  try {
    const feature = config.features.find(f => f.id === id);
    if (feature) {
      const module = await import(feature.module);
      if (current !== revision) return;
      // Detached view prevents a slow request from overwriting a newly selected page.
      const view = ui.el('div'); root.append(view);
      const dispose = await module.mount(view, {api, config, device, ui});
      if (current !== revision) dispose?.(); else cleanup = dispose;
    } else {
      ui.heading(root, '你好，继续走下去。', '记录每一次运动，看见属于自己的变化。');
      const {sessions} = await api('/api/sessions');
      if (current !== revision) return;
      const personal = sessions.filter(s => s.eligible);
      const grid = ui.el('div', null, 'grid stats');
      grid.append(ui.metric('穿戴运动记录', personal.length, '次'),
        ui.metric('累计记录时长', ui.number(personal.reduce((n, s) => n + s.metrics.duration_s, 0) / 60), '分钟'),
        ui.metric('最近一次', personal.length ? new Date(personal[0].started_at * 1000).toLocaleDateString('zh-CN') : '—'));
      root.append(grid);
      if (!sessions.length) ui.empty(root, '从你的第一次记录开始', '连接外骨骼完成一次运动后，在行走档案中收录记录。');
      const cards = ui.el('div', null, 'grid');
      for (const f of config.features) {
        const a = ui.el('a', null, 'card feature'); a.href = `#${f.id}`;
        a.append(ui.el('h2', f.title), ui.el('p', f.description, 'muted'), ui.el('span', '打开 →', 'accent')); cards.append(a);
      }
      root.append(cards);
    }
  } catch (e) { if (current === revision) ui.empty(root, '暂时无法打开', e.message); }
}
device.addEventListener('change', () => {
  const node = document.querySelector('#connection');
  node.textContent = device.fresh ? '设备数据已连接' : '未连接设备'; node.classList.toggle('connected', device.fresh);
});
window.addEventListener('hashchange', render);
window.addEventListener('pagehide', () => { cleanup?.(); device.close(); });
render();
