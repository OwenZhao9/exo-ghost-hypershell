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
      const hero = ui.el('section', null, 'home-hero');
      const intro = ui.el('div');
      intro.append(ui.el('p', 'GHOST / MOVEMENT STUDIO', 'eyebrow'),
        ui.el('h1', '从这里，开始下一步。'),
        ui.el('p', '设备状态、运动模式和每次留下的记录，都在这里。', 'muted'));
      const status = ui.el('div', null, 'home-status');
      const statusMain = ui.el('div'), statusTitle = ui.el('strong'), statusDetail = ui.el('p');
      statusMain.append(ui.el('span', '当前数据', 'home-status-label'), statusTitle, statusDetail);
      status.append(statusMain, ui.el('p', config.control_enabled ? '运动操作需要真机就绪，并由你手动开始。' : '当前为只读查看。运动操作请使用控制台。', 'status-detail'));
      intro.append(status);
      const visual = ui.el('div', null, 'home-visual');
      const productImage = ui.el('img');
      productImage.src = '/assets/hypershell-front.webp';
      productImage.alt = 'Hypershell X Max S 外骨骼正面';
      visual.append(productImage);
      hero.append(intro, visual); root.append(hero);
      const updateHomeStatus = () => {
        statusTitle.textContent = device.fresh ? '实时数据已接收' : '等待设备数据';
        const body = device.status?.body;
        const source = body === 'real' ? '真机' : body === 'sim' ? '仿真' : '来源待确认';
        const profile = device.status?.profile === 'table' ? ' · 桌面标定' : device.status?.profile === 'wearing' ? ' · 穿戴' : '';
        statusDetail.textContent = device.fresh ? `数据来源：${source}${profile}` : '连接后显示当前设备数据。';
      };
      device.addEventListener('change', updateHomeStatus);
      cleanup = () => device.removeEventListener('change', updateHomeStatus);
      updateHomeStatus();
      const {sessions} = await api('/api/sessions');
      if (current !== revision) return;
      const personal = sessions.filter(s => s.eligible);
      const grid = ui.el('div', null, 'stat-strip');
      grid.append(ui.metric('穿戴运动记录', personal.length, '次'),
        ui.metric('累计记录时长', ui.number(personal.reduce((n, s) => n + s.metrics.duration_s, 0) / 60), '分钟'),
        ui.metric('最近一次', personal.length ? new Date(personal[0].started_at * 1000).toLocaleDateString('zh-CN') : '—'));
      root.append(grid);
      const section = ui.el('div', null, 'section-head');
      section.append(ui.el('h2', '选择一项任务'), ui.el('span', '运动 / 档案 / 偏好 / 成长 / 眼镜'));
      root.append(section);
      const cards = ui.el('div', null, 'grid feature-grid');
      config.features.forEach((f, i) => {
        const a = ui.el('a', null, 'card feature'); a.href = `#${f.id}`;
        if (f.id === 'modes') a.classList.add('feature-primary');
        const top = ui.el('div', null, 'feature-top');
        top.append(ui.el('span', String(i + 1).padStart(2, '0'), 'feature-number'), ui.el('span', '↗', 'feature-arrow'));
        a.append(top, ui.el('h2', f.title), ui.el('p', f.description, 'muted')); cards.append(a);
      });
      root.append(cards);
      if (!sessions.length) ui.empty(root, '还没有穿戴运动记录', '完成运动并收录记录后，活动统计会显示在上方。');
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
