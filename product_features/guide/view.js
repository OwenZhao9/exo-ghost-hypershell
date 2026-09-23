export async function mount(root, {api, ui}) {
  ui.heading(root, '眼镜看一看', '连续拍照时，每张照片和识别结果依次排列。');
  const note = ui.el('p', '每条判断只对应那张照片，不能判断此刻道路是否可通行。', 'inline-note');
  root.append(note);
  const demo = ui.card('拍照演示'), demoState = ui.el('p', '', 'guide-demo-state');
  const demoDetail = ui.el('p', '', 'muted'), demoActions = ui.el('div', null, 'guide-demo-actions');
  const start = ui.button('开始拍照演示', async () => {
    start.disabled = true;
    try { showDemo(await api('/api/guide/demo/start', {})); }
    catch (error) { demoDetail.textContent = error.message; start.disabled = false; }
  }, 'button primary');
  const stop = ui.button('停止', async () => {
    stop.disabled = true;
    try { showDemo(await api('/api/guide/demo/stop', {})); }
    catch (error) { demoDetail.textContent = error.message; stop.disabled = false; }
  }, 'button');
  demoActions.append(start, stop); demo.append(demoState, demoDetail, demoActions); root.append(demo);
  const timeline = ui.card('拍照记录'), captures = ui.el('div', null, 'guide-capture-list');
  const captureEmpty = ui.el('p', '开始演示后，照片会依次显示在这里。', 'muted');
  captures.append(captureEmpty); timeline.append(captures); root.append(timeline);
  const panel = ui.card('照片库 · 手动描述'), list = ui.el('div', null, 'guide-list');
  const photoEmpty = ui.el('p', '正在读取照片。', 'muted');
  list.append(photoEmpty); panel.append(list); root.append(panel);
  const result = ui.card('画面描述'), resultText = ui.el('p', '选择照片后，点击“描述这张照片”。', 'muted');
  result.append(resultText); root.append(result);
  const refresh = ui.button('刷新照片', () => load());
  root.insertBefore(refresh, panel);

  let disposed = false, loading = false;
  const captureRows = new Map(), photoRows = new Map();
  function showDemo(state) {
    if (!state.available) { demo.hidden = true; timeline.hidden = true; return; }
    demo.hidden = false;
    start.disabled = state.running; stop.disabled = !state.running;
    const phase = {idle: '已停止', capturing: '正在拍照', analyzing: '正在识别',
      scanning: '正在连接眼镜', waiting: '等待下一张', stopping: '正在停止', error: '需要重试'}[state.phase] || '等待中';
    demoState.textContent = `${phase} · 本轮 ${state.captured_count}/${state.max_frames} 张`;
    demoDetail.textContent = [state.error,
      '语音录音尚未接入；请勿依据演示判断行走。'].filter(Boolean).join('\n');
  }

  function showCaptures(history) {
    for (const shot of history) {
      let row = captureRows.get(shot.filename);
      if (!row) {
        captureEmpty.remove();
        const card = ui.el('article', null, 'guide-capture-item');
        const title = ui.el('h3', `第 ${captureRows.size + 1} 张 · ${ui.date(shot.captured_at)}`);
        const image = ui.el('img');
        image.className = 'guide-capture-image'; image.alt = `眼镜拍摄的第 ${captureRows.size + 1} 张照片`;
        image.hidden = true;
        const message = ui.el('p', '正在读取照片。', 'muted');
        const detail = ui.el('p', '', 'muted');
        const body = ui.el('div', null, 'guide-capture-body'); body.append(title, message, detail);
        card.append(image, body); captures.append(card);
        row = {message, detail}; captureRows.set(shot.filename, row);
        api('/api/guide/image', {filename: shot.filename}).then(data => {
          if (!disposed) { image.src = data.src; image.hidden = false; }
        }).catch(() => {
          if (!disposed) body.append(ui.el('p', '这张照片暂时无法读取。', 'muted'));
        });
      }
      const direction = shot.direction === 'left' ? '画面左侧较空（演示）' :
        shot.direction === 'right' ? '画面右侧较空（演示）' : '无法判断方向';
      row.message.className = shot.state === 'complete' ? 'guide-capture-result' : 'muted';
      row.message.textContent = shot.state === 'analyzing' ? '正在识别这张照片…' :
        shot.state === 'interrupted' ? '识别未完成' :
        shot.state === 'error' ? '识别失败' : direction;
      row.detail.textContent = [shot.description, shot.error,
        `拍照 ${shot.capture_seconds} 秒`,
        shot.analysis_seconds != null ? `识别 ${shot.analysis_seconds} 秒` : ''].filter(Boolean).join(' · ');
    }
  }

  async function load() {
    if (loading || disposed) return;
    loading = true;
    try {
    const [data, state] = await Promise.all([api('/api/guide/photos'), api('/api/guide/demo')]);
    if (disposed) return;
    showDemo(state);
    showCaptures(state.history || []);
    if (!data.capture_available) {
      photoEmpty.textContent = '尚未接入眼镜照片目录。';
      return;
    }
    if (!data.photos.length) {
      photoEmpty.textContent = '还没有眼镜照片。';
      return;
    }
    photoEmpty.remove();
    for (const photo of data.photos.slice().reverse()) {
      if (photoRows.has(photo.filename)) continue;
      const row = ui.el('div', null, 'guide-photo-row'), details = ui.el('div');
      const age = Date.now() / 1000 - photo.captured_at;
      details.append(ui.el('strong', photo.filename),
        ui.el('p', `保存时间：${ui.date(photo.captured_at)}${age > 30 ? ' · 历史照片' : ''}`, 'muted'));
      const button = ui.button('描述这张照片', async () => {
        resultText.textContent = '正在识别选中的照片…';
        try {
          const answer = await api('/api/guide/describe', {filename: photo.filename});
          resultText.textContent = `${answer.description}\n\n照片保存时间：${ui.date(answer.captured_at)}。${answer.historical ? '这是一张历史照片，不能代表当前环境。' : '画面可能已变化，请勿仅凭描述行动。'}`;
        } catch (error) {
          resultText.textContent = error.message;
        }
      }, 'button primary');
      button.disabled = !data.vision_available;
      row.append(details, button); list.append(row); photoRows.set(photo.filename, row);
    }
    } catch (error) {
      if (!disposed) demoDetail.textContent = error.message;
    } finally { loading = false; }
  }
  await load();
  const timer = setInterval(load, 2000);
  return () => { disposed = true; clearInterval(timer); };
}
