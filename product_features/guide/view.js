export async function mount(root, {api, ui}) {
  ui.heading(root, '眼镜看一看', '选择眼镜拍到的照片，获取画面描述。');
  const note = ui.el('p', '识别内容仅对应选中的照片，不能判断此刻道路是否可通行。', 'inline-note');
  root.append(note);
  const panel = ui.card('眼镜照片'), list = ui.el('div', null, 'guide-list');
  panel.append(list); root.append(panel);
  const result = ui.card('画面描述'), resultText = ui.el('p', '选择照片后，点击“描述这张照片”。', 'muted');
  result.append(resultText); root.append(result);
  const refresh = ui.button('刷新照片', () => load());
  root.insertBefore(refresh, panel);

  async function load() {
    const data = await api('/api/guide/photos');
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
  }
  await load();
}
