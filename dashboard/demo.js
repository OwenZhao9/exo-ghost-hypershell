(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const canvas = $('waist-chart');
  const ctx = canvas.getContext('2d');
  const samples = [];
  const windowMs = 30000;
  let socket = null;
  let status = null;
  let lastSampleAt = 0;
  let retryTimer = null;
  let wsPort = 0;
  let sourceIsReal = false;

  function label(id, value) { $(id).textContent = value; }
  function number(value, digits = 1, suffix = '°') {
    return Number.isFinite(value) ? `${value.toFixed(digits)}${suffix}` : '—';
  }
  function connection(text, style) {
    const node = $('connection');
    node.textContent = text;
    node.className = `connection ${style}`;
  }
  function deviceState() {
    if (!sourceIsReal) return ['数据来源未确认', '当前服务无法确认为真机'];
    if (Date.now() - lastSampleAt > 2000 || !socket || socket.readyState !== WebSocket.OPEN) {
      return ['等待真机数据', '曲线与读数暂停更新'];
    }
    const state = status?.state;
    if (state === 'LEGS_OFF' || status?.legs_offline) return ['腿板数据无效', '腰部数据仍可查看'];
    if (state === 'RECONN') return ['串口重连中', '等待新的真机数据'];
    if (state === 'TRIPPED') return ['急停锁存', '控制已停止'];
    if (state === 'QUIET') return ['安全等待', '暂不接受施力指令'];
    if (state === 'ARMED') return ['真机已连接', '关节数据已就绪'];
    return ['等待设备就绪', '正在接收真机状态'];
  }
  function refresh() {
    const fresh = sourceIsReal && socket?.readyState === WebSocket.OPEN && Date.now() - lastSampleAt < 2000;
    const legValid = fresh && status && !status.legs_offline && !['LEGS_OFF', 'RECONN', 'OFFLINE'].includes(status.state);
    const [state, detail] = deviceState();
    label('device-state', state);
    label('state-detail', detail);
    label('sample-rate', fresh && Number.isFinite(status?.hz) ? `${Math.round(status.hz)} Hz` : '—');
    if (fresh && status) {
      const reflex = status.reflex || {};
      label('reflex-state', status.state === 'TRIPPED' ? '急停已触发' : Number.isFinite(reflex.scale) && reflex.scale < 0.99 ? '正在限制输出' : '逐帧监测中');
      label('reflex-detail', reflex.binding_label || '检查运动边界与当前输出');
      const decision = status.decision || {};
      const strategy = { zero: '松劲', resist: '阻尼', assist: '助力' };
      label('decision-state', decision.last?.want ? `建议${strategy[decision.last.want] || decision.last.want}` : '等待运动窗口');
      label('decision-detail', decision.autopilot ? '自动执行已开启' : '建议由人确认，不自动下发');
      const memory = status.memory || {};
      const hits = memory.last?.hits;
      label('memory-state', Array.isArray(hits) ? (hits.length ? `找到 ${hits.length} 条经验` : '尚无匹配经验') : '等待事件');
      label('memory-detail', '只显示检索状态，不展示私人记录');
    } else {
      for (const id of ['reflex-state', 'decision-state', 'memory-state']) label(id, '等待数据');
      label('reflex-detail', '逐帧检查运动边界');
      label('decision-detail', '根据运动窗口提出策略建议');
      label('memory-detail', '异常时检索处置经验');
    }
    $('leg-note').textContent = legValid
      ? '左右髋关节正在显示现场传感器数据。'
      : fresh && status?.legs_offline
        ? '当前双腿关节数据无效；腰部曲线仍来自现场真机。'
        : '等待有效的左右髋关节数据。';
    $('leg-note').classList.toggle('warn', !legValid);
    if (!fresh) {
      samples.length = 0;
      for (const id of ['pitch', 'roll', 'yaw', 'left-angle', 'right-angle']) label(id, '—');
      for (const id of ['left-speed', 'right-speed']) label(id, '关节数据待确认');
      $('chart-empty').hidden = false;
      return;
    }
    if (!legValid) {
      label('left-angle', '—'); label('right-angle', '—');
      label('left-speed', '关节数据待确认'); label('right-speed', '关节数据待确认');
    }
  }
  function receiveSample(v) {
    if (!sourceIsReal || !Array.isArray(v) || v.length < 10) return;
    const [left, right, leftSpeed, rightSpeed, , , , pitch, roll, yaw] = v;
    if (![pitch, roll, yaw].every(Number.isFinite)) return;
    const now = Date.now();
    lastSampleAt = now;
    if (samples.length && now - samples[samples.length - 1].at > 500) samples.length = 0;
    if (!samples.length || now - samples[samples.length - 1].at >= 40) samples.push({ at: now, pitch, roll });
    while (samples.length && samples[0].at < now - windowMs) samples.shift();
    label('pitch', number(pitch)); label('roll', number(roll)); label('yaw', number(yaw));
    if (status && !status.legs_offline && !['LEGS_OFF', 'RECONN', 'OFFLINE'].includes(status.state)) {
      label('left-angle', number(left)); label('right-angle', number(right));
      label('left-speed', Number.isFinite(leftSpeed) ? `${leftSpeed.toFixed(1)} °/s` : '—');
      label('right-speed', Number.isFinite(rightSpeed) ? `${rightSpeed.toFixed(1)} °/s` : '—');
    }
    $('chart-empty').hidden = samples.length > 0;
    refresh();
  }
  function draw() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (!width || !height) return;
    const pixelWidth = Math.round(width * dpr), pixelHeight = Math.round(height * dpr);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth; canvas.height = pixelHeight;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const padX = 44, top = 23, bottom = height - 32;
    const max = Math.max(30, ...samples.flatMap(s => [Math.abs(s.pitch), Math.abs(s.roll)]));
    const bound = Math.ceil(max / 10) * 10;
    ctx.font = '12px -apple-system, sans-serif';
    ctx.textAlign = 'right';
    for (let step = -2; step <= 2; step++) {
      const y = top + (2 - step) / 4 * (bottom - top);
      ctx.strokeStyle = step === 0 ? '#35513b' : '#203327';
      ctx.beginPath(); ctx.moveTo(padX, y); ctx.lineTo(width - 16, y); ctx.stroke();
      ctx.fillStyle = '#89a58d';
      ctx.fillText(`${Math.round(step * bound / 2)}°`, padX - 9, y + 4);
    }
    const now = Date.now();
    const x = at => padX + (at - (now - windowMs)) / windowMs * Math.max(1, width - padX - 16);
    const y = value => top + (bound - value) / (2 * bound) * (bottom - top);
    for (const [field, color] of [['pitch', '#d6f58a'], ['roll', '#62d6d4']]) {
      ctx.strokeStyle = color; ctx.lineWidth = 2.4; ctx.lineJoin = 'round';
      ctx.beginPath();
      samples.forEach((sample, index) => {
        if (index === 0) ctx.moveTo(x(sample.at), y(sample[field]));
        else ctx.lineTo(x(sample.at), y(sample[field]));
      });
      if (samples.length === 1) { ctx.arc(x(samples[0].at), y(samples[0][field]), 3, 0, Math.PI * 2); }
      ctx.stroke();
    }
    ctx.fillStyle = '#89a58d'; ctx.textAlign = 'right';
    ctx.fillText('最近 30 秒', width - 17, height - 11);
  }
  function connect() {
    clearTimeout(retryTimer);
    if (!wsPort || !sourceIsReal) return;
    const host = location.hostname || '127.0.0.1';
    socket = new WebSocket(`ws://${host}:${wsPort}`);
    socket.onopen = () => connection('真机数据通道已连接', 'good');
    socket.onmessage = event => {
      let message;
      try { message = JSON.parse(event.data); } catch (_) { return; }
      if (message.k === 'st') {
        status = message;
        if (message.body && message.body !== 'real') {
          sourceIsReal = false;
          connection('数据来源不是当前真机', 'bad');
          socket.close();
        }
        refresh();
      } else if (message.k === 's') receiveSample(message.v);
    };
    socket.onclose = () => {
      socket = null; lastSampleAt = 0; samples.length = 0;
      connection(sourceIsReal ? '真机数据断开，正在重连' : '等待真机服务', 'bad');
      refresh();
      if (sourceIsReal) retryTimer = setTimeout(connect, 1000);
    };
    socket.onerror = () => socket.close();
  }
  async function start() {
    try {
      const response = await fetch('runtime-config.json', { cache: 'no-store' });
      if (response.ok) {
        const config = await response.json();
        if (config.body !== 'real' || !Number.isInteger(config.ws_port) || config.ws_port < 1 || config.ws_port > 65535) {
          throw new Error('需要连接真机服务');
        }
        wsPort = config.ws_port;
      } else if (response.status === 404 && location.port === '8000') {
        // 兼容当前已在 8000/8765 运行的旧版真机服务，不触碰它独占的串口。
        wsPort = 8765;
      } else {
        throw new Error('服务配置不可用');
      }
      sourceIsReal = true;
      connect();
    } catch (error) {
      connection(error.message, 'bad');
      label('state-detail', '打开真机控制服务后自动刷新页面');
    }
  }
  start();
  setInterval(() => { refresh(); draw(); }, 100);
})();
