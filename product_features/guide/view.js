import {createVoicePlayer} from './voice.js';

export async function mount(root, {api, config, device, ui}) {
  ui.heading(root, '眼镜看一看', '连续拍照时，最新照片显示在最上方，识别结果标注在对应照片上。');
  const note = ui.el('p', '每条判断只对应那张照片，不能判断此刻道路是否可通行。', 'inline-note');
  root.append(note);
  const demo = ui.card('拍照演示'), demoState = ui.el('p', '', 'guide-demo-state');
  const demoDetail = ui.el('p', '', 'muted'), demoActions = ui.el('div', null, 'guide-demo-actions');
  let voiceArmed = false, voiceStartedAt = 0, voiceError = '', playedCue = '', lastRunning = false;
  let motorArmed = false, motorStartedAt = 0, motorInfo = '', motorStopTimer = null;
  let pendingMotor = null;
  const seenStates = new Map();
  const voice = createVoicePlayer({
    onError: message => {
      voiceArmed = false;
      voiceError = message;
      showDemo(currentState);
    },
    onPlayed: cue => {
      playedCue = {left: '向左', right: '向右', unknown: '无法判断', stop: '演示已停止'}[cue];
      showDemo(currentState);
    },
  });
  let currentState = null;
  function disarmMotor() {
    clearTimeout(motorStopTimer); motorStopTimer = null;
    pendingMotor = null;
    if (!motorArmed) return;
    motorArmed = false;
    try { device.send({op: 'zero'}); }
    catch { /* Timed motor cue also returns to zero inside the control service. */ }
    if (motorButton) motorButton.textContent = '开启抬腿演示';
  }
  const start = ui.button('开始拍照演示', async () => {
    start.disabled = true;
    voiceArmed = true;
    voiceStartedAt = Date.now() / 1000;
    voiceError = '';
    playedCue = '';
    try { showDemo(await api('/api/guide/demo/start', {})); }
    catch (error) {
      voiceArmed = false;
      demoDetail.textContent = error.message;
      start.disabled = false;
    }
  }, 'button primary');
  const stop = ui.button('停止', async () => {
    stop.disabled = true;
    disarmMotor();
    try {
      const state = await api('/api/guide/demo/stop', {});
      voiceArmed = false;
      voice.interrupt('stop');
      showDemo(state);
    }
    catch (error) { demoDetail.textContent = error.message; stop.disabled = false; }
  }, 'button');
  const enableVoice = ui.button('开启语音并试听', () => {
    voiceArmed = true;
    voiceStartedAt = Date.now() / 1000;
    voiceError = '';
    playedCue = '';
    voice.interrupt('unknown');
    showDemo(currentState);
  }, 'button');
  const motorButton = config.guide_motor_demo ? ui.button('开启抬腿演示', () => {
    if (motorArmed) {
      disarmMotor();
      motorInfo = '电机演示已关闭。';
    } else if (!currentState?.running) {
      motorInfo = '请先开始拍照演示。';
    } else if (!device.ready || device.status?.profile !== 'table' ||
               device.status?.policy !== 'zero') {
      motorInfo = '请确认支架上的真机已就绪，且当前模式为松劲。';
    } else {
      motorArmed = true;
      motorStartedAt = Date.now() / 1000;
      motorInfo = '抬腿演示已开启；仅对之后拍摄并识别的照片动作。';
      motorButton.textContent = '关闭抬腿演示';
    }
    showDemo(currentState);
  }, 'button') : null;
  const motorEstop = config.guide_motor_demo ? ui.button('电机急停', () => {
    try {
      device.send({op: 'estop'});
      clearTimeout(motorStopTimer); motorStopTimer = null;
      motorArmed = false; pendingMotor = null;
      motorButton.textContent = '开启抬腿演示';
      motorInfo = '已发送电机急停。';
    } catch (error) { motorInfo = error.message; }
    showDemo(currentState);
  }, 'button danger') : null;
  demoActions.append(start, stop, enableVoice);
  if (motorButton) demoActions.append(motorButton, motorEstop);
  demo.append(demoState, demoDetail, demoActions); root.append(demo);
  const updateMotor = () => {
    if (!motorArmed) return;
    if (!device.ready || device.status?.profile !== 'table') {
      disarmMotor();
      motorInfo = '设备状态变化，电机演示已关闭。';
      showDemo(currentState);
      return;
    }
    if (pendingMotor && device.status?.policy === 'guide_cue') {
      motorInfo = pendingMotor.direction === 'right' ? '左腿抬起提示执行中。' : '右腿抬起提示执行中。';
      pendingMotor = null;
      showDemo(currentState);
    } else if (pendingMotor && Date.now() - pendingMotor.sentAt > 2500) {
      disarmMotor();
      motorInfo = '控制服务未确认抬腿请求，演示已关闭。';
      showDemo(currentState);
    }
  };
  if (motorButton) device.addEventListener('change', updateMotor);
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
    if (!state) return;
    currentState = state;
    if (!state.available) { demo.hidden = true; timeline.hidden = true; return; }
    if (voiceArmed && lastRunning && !state.running) {
      voice.enqueue('stop');
      voiceArmed = false;
    }
    if (motorArmed && lastRunning && !state.running) {
      motorStopTimer = setTimeout(() => {
        disarmMotor();
        motorInfo = '本轮结束，电机演示已关闭。';
        showDemo(currentState);
      }, 4500);
    }
    lastRunning = state.running;
    demo.hidden = false;
    start.disabled = state.running; stop.disabled = !state.running;
    const phase = state.phase === 'stopping' ? '正在停止' :
      state.capture_running && state.pending_count ? `正在拍照，同时识别 ${state.pending_count} 张` :
      state.capture_running ? '正在拍照' :
      state.analysis_running ? `正在识别剩余 ${state.pending_count} 张` :
      state.phase === 'error' ? '需要重试' : '已停止';
    demoState.textContent = `${phase} · 本轮 ${state.captured_count}/${state.max_frames} 张`;
    demoDetail.textContent = [state.error, voiceError,
      voiceArmed ? '语音已开启，将从电脑当前音频输出设备播放。' :
        '点击“开始”会开启语音；也可试听。',
      playedCue ? `最近语音：${playedCue}` : '',
      config.guide_motor_demo ? (motorArmed ? '电机演示已开启。' : '电机演示未开启。') : '',
      motorInfo,
      '请勿依据演示判断行走。'].filter(Boolean).join('\n');
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
        const overlay = ui.el('div', null, 'guide-annotation-layer');
        const visual = ui.el('div', null, 'guide-capture-visual'); visual.append(image, overlay);
        const message = ui.el('p', '正在读取照片。', 'muted');
        const detail = ui.el('p', '', 'muted');
        const body = ui.el('div', null, 'guide-capture-body'); body.append(title, message, detail);
        card.append(visual, body); captures.prepend(card);
        row = {message, detail, overlay, annotationSignature: null};
        captureRows.set(shot.filename, row);
        api('/api/guide/image', {filename: shot.filename}).then(data => {
          if (!disposed) { image.src = data.src; image.hidden = false; }
        }).catch(() => {
          if (!disposed) body.append(ui.el('p', '这张照片暂时无法读取。', 'muted'));
        });
      }
      const direction = shot.direction === 'left' ? '画面左侧较空（演示）' :
        shot.direction === 'right' ? '画面右侧较空（演示）' : '无法判断方向';
      row.message.className = shot.state === 'complete' ? 'guide-capture-result' : 'muted';
      row.message.textContent = shot.state === 'queued' ? '等待识别这张照片…' :
        shot.state === 'analyzing' ? '正在识别这张照片…' :
        shot.state === 'interrupted' ? '识别未完成' :
        shot.state === 'error' ? '识别失败' : direction;
      row.detail.textContent = [shot.description, shot.error,
        `拍照 ${shot.capture_seconds} 秒`,
        shot.analysis_seconds != null ? `识别 ${shot.analysis_seconds} 秒` : ''].filter(Boolean).join(' · ');
      const signature = JSON.stringify([shot.state, shot.direction, shot.annotations]);
      if (row.annotationSignature !== signature) {
        row.annotationSignature = signature;
        row.overlay.replaceChildren();
        if (shot.state === 'complete' && shot.analysis_seconds != null) {
          const badge = shot.direction === 'left' ? '左侧较空' :
            shot.direction === 'right' ? '右侧较空' : '无法判断';
          const annotations = Array.isArray(shot.annotations) ? shot.annotations : [];
          if (!annotations.length) row.overlay.append(ui.el('span', badge, 'guide-annotation-badge'));
          for (const item of annotations) {
            if (!item || typeof item !== 'object' || typeof item.label !== 'string') continue;
            const box = item.box;
            if (!Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite)) continue;
            const [x, y, w, h] = box;
            if (x < 0 || y < 0 || w <= 0 || h <= 0 || x + w > 1 || y + h > 1) continue;
            const marker = ui.el('div', null, 'guide-annotation-box');
            marker.style.left = `${x * 100}%`; marker.style.top = `${y * 100}%`;
            marker.style.width = `${w * 100}%`; marker.style.height = `${h * 100}%`;
            marker.append(ui.el('span', item.label, 'guide-annotation-label'));
            row.overlay.append(marker);
          }
        }
      }
      const previousState = seenStates.get(shot.filename);
      if (voiceArmed && shot.state === 'complete' && previousState !== 'complete' &&
          (previousState !== undefined || shot.captured_at >= voiceStartedAt - 1)) {
        voice.enqueue(shot.direction === 'left' || shot.direction === 'right' ?
          shot.direction : 'unknown');
      }
      if (motorArmed && shot.state === 'complete' && previousState !== 'complete' &&
          Number.isFinite(shot.capture_started_at) && shot.capture_started_at >= motorStartedAt) {
        if (shot.direction === 'left' || shot.direction === 'right') {
          if (Date.now() / 1000 - shot.captured_at > 60 ||
              !Number.isFinite(shot.analyzed_at) || Date.now() / 1000 - shot.analyzed_at > 5) {
            motorInfo = '照片结果已经过期，本次不动作。';
          } else {
            try {
              device.send({op: 'guide_cue', direction: shot.direction});
              pendingMotor = {direction: shot.direction, sentAt: Date.now()};
              motorInfo = shot.direction === 'right' ? '已请求左腿抬起，等待设备确认。' : '已请求右腿抬起，等待设备确认。';
            } catch (error) { motorInfo = error.message; }
          }
        } else { motorInfo = '无法判断方向，本次不动作。'; }
        showDemo(currentState);
      }
      seenStates.set(shot.filename, shot.state);
    }
  }

  async function load() {
    if (loading || disposed) return;
    loading = true;
    try {
    const [data, state] = await Promise.all([api('/api/guide/photos'), api('/api/guide/demo')]);
    if (disposed) return;
    showCaptures(state.history || []);
    showDemo(state);
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
      row.append(details, button); list.prepend(row); photoRows.set(photo.filename, row);
    }
    } catch (error) {
      if (!disposed) demoDetail.textContent = error.message;
    } finally { loading = false; }
  }
  await load();
  const timer = setInterval(load, 2000);
  return () => { disposed = true; clearInterval(timer); disarmMotor();
    if (motorButton) device.removeEventListener('change', updateMotor);
    voice.interrupt(); };
}
