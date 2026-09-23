export function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
export function heading(root, title, subtitle) {
  const h = el('section', null, 'page-heading');
  h.append(el('p', 'MY GHOST', 'eyebrow'), el('h1', title), el('p', subtitle, 'muted'));
  root.append(h);
}
export function empty(root, title, description) {
  const box = el('div', null, 'empty');
  box.append(el('div', '↗', 'empty-icon'), el('h2', title), el('p', description, 'muted'));
  root.append(box); return box;
}
export function card(title) { const c = el('section', null, 'card'); if (title) c.append(el('h2', title)); return c; }
export function metric(label, value, unit = '') {
  const c = card(); c.classList.add('metric');
  c.append(el('p', label, 'muted'), el('strong', value ?? '—'), el('span', unit, 'unit')); return c;
}
export function button(label, fn, cls = 'button') {
  const b = el('button', label, cls); b.type = 'button';
  b.onclick = async () => { b.disabled = true; try { await fn(); } catch(e) { notify(e.message); } finally { if (b.isConnected) b.disabled = false; } };
  return b;
}
let noticeTimer;
export function notify(text) {
  const n = document.querySelector('#notice'); n.textContent = text; n.hidden = false;
  clearTimeout(noticeTimer); noticeTimer = setTimeout(() => n.hidden = true, 5500);
}
export const date = t => new Date(t * 1000).toLocaleString('zh-CN');
export const number = (n, digits = 1) => Number.isFinite(n) ? n.toFixed(digits) : '—';
export function field(label, input) { const wrap = el('label', null, 'field'); wrap.append(el('span', label), input); return wrap; }
export function input(value = '', type = 'text') { const i = el('input'); i.type = type; i.value = value; return i; }
