export async function mount(root, {api, ui}) {
  ui.heading(root, '眼镜看一看', '查看眼镜拍到的照片，或开始拍照演示。');
  const note = ui.el('p', '识别内容仅对应选中的照片，不能判断此刻道路是否可通行。', 'inline-note');
  root.append(note);
  const preview = ui.card('最新照片'), previewImage = ui.el('img'), previewTime = ui.el('p', '等待眼镜照片。', 'muted');
  previewImage.className = 'guide-preview-image'; previewImage.alt = '眼镜最近拍到的照片'; previewImage.hidden = true;
  preview.append(previewImage, previewTime); root.append(preview);
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
  demoActions.append(start, stop); demo.append(demoState, demoDetail, demoActions); root.insertBefore(demo, preview);
  const panel = ui.card('眼镜照片'), list = ui.el('div', null, 'guide-list');
  panel.append(list); root.append(panel);
  const result = ui.card('画面描述'), resultText = ui.el('p', '选择照片后，点击“描述这张照片”。', 'muted');
  result.append(resultText); root.append(result);
  const refresh = ui.button('刷新照片', () => load());
  root.insertBefore(refresh, panel);

  let disposed = false, loading = false, latestName = null, listSignature = null;
  function showDemo(state) {
    if (!state.available) { demo.hidden = true; return; }
    demo.hidden = false;
    start.disabled = state.running; stop.disabled = !state.running;
    const direction = state.direction === 'left' ? '画面左侧较空（演示）' :
      state.direction === 'right' ? '画面右侧较空（演示）' : '无法判断方向';
    const phase = {idle: '已停止', capturing: '正在拍照', analyzing: '正在识别',
      scanning: '正在连接眼镜', waiting: '等待下一张', stopping: '正在停止', error: '需要重试'}[state.phase] || '等待中';
    demoState.textContent = `${phase} · ${direction}`;
    const timings = [state.capture_seconds != null ? `拍照 ${state.capture_seconds} 秒` : '',
      state.analysis_seconds != null ? `识别 ${state.analysis_seconds} 秒` : '',
      `${state.captured_count}/${state.max_frames} 张`].filter(Boolean).join('，');
    demoDetail.textContent = [state.description, timings, state.error,
      '语音录音尚未接入；请勿依据演示判断行走。'].filter(Boolean).join('\n');
  }

  async function load() {
    if (loading || disposed) return;
    loading = true;
    try {
    const data = await api('/api/guide/photos');
    const state = await api('/api/guide/demo');
    if (disposed) return;
    showDemo(state);
    const name = data.photos[0]?.filename || null;
    if (name && name !== latestName) {
      const image = await api('/api/guide/latest');
      if (disposed) return;
      if (image.photo) {
        previewImage.src = image.photo.src; previewImage.hidden = false;
        previewTime.textContent = `拍摄时间：${ui.date(image.photo.captured_at)}`;
        latestName = image.photo.filename;
      }
    }
    const signature = data.photos.map(photo => photo.filename).join('|') + `:${data.vision_available}`;
    if (signature === listSignature) return;
    listSignature = signature;
    list.replaceChildren();
    if (!data.capture_available) {
      list.append(ui.el('p', '尚未接入眼镜照片目录。', 'muted'));
      return;
    }
    if (!data.photos.length) {
      list.append(ui.el('p', '还没有眼镜照片。用眼镜拍照后刷新此处。', 'muted'));
      return;
    }
    if (!data.vision_available) {
      list.append(ui.el('p', '视觉接口尚未配置，照片暂时只能查看列表。', 'muted'));
    }
    for (const photo of data.photos) {
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
      row.append(details, button); list.append(row);
    }
    } catch (error) {
      if (!disposed) demoDetail.textContent = error.message;
    } finally { loading = false; }
  }
  await load();
  const timer = setInterval(load, 2000);
  return () => { disposed = true; clearInterval(timer); };
}
