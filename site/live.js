const STALE_MS = 1500;
const RETRY_MS = 1000;

export function parseFrame(message) {
  if (message?.k !== "s" || !Array.isArray(message.v) || message.v.length < 10)
    return null;
  const values = message.v;
  const fields = [0, 1, 2, 3, 4, 5, 7, 8, 9];
  if (fields.some((index) => !Number.isFinite(values[index]))) return null;
  return {
    left: values[0],
    right: values[1],
    leftSpeed: values[2],
    rightSpeed: values[3],
    leftTorque: values[4],
    rightTorque: values[5],
    pitch: values[7],
    roll: values[8],
    yaw: values[9],
    gx: Number.isFinite(values[10]) ? values[10] : null,
    gy: Number.isFinite(values[11]) ? values[11] : null,
    gz: Number.isFinite(values[12]) ? values[12] : null,
  };
}

export function liveState(status, frame, ageMs, connected) {
  if (!connected) return { label: "等待设备连接", level: "offline", usable: false };
  if (status.body === "sim")
    return { label: "当前为演示画面", level: "offline", usable: false };
  if (status.state === "TRIPPED" && (!frame || ageMs >= STALE_MS || status.legs_offline))
    return { label: "设备保护已触发 · 需人工恢复", level: "warn", usable: false };
  if (status.state === "LEGS_OFF" || status.legs_offline)
    return { label: "设备读数异常", level: "warn", usable: false };
  if (status.state === "RECONN" || status.state === "OFFLINE")
    return { label: "正在连接设备", level: "offline", usable: false };
  if (!frame || ageMs >= STALE_MS)
    return { label: "等待设备数据", level: "offline", usable: false };
  if (status.state === "TRIPPED")
    return { label: "设备已停止 · 当前读数", level: "warn", usable: true };
  if (status.body !== "real")
    return { label: "设备来源待确认", level: "warn", usable: true };
  if (status.state === "QUIET")
    return { label: "设备准备中", level: "warn", usable: true };
  return { label: "设备已连接", level: "online", usable: true };
}

export function controlState({ status, frame, frameAgeMs, statusAgeMs, connected, confirmed }) {
  if (connected && status.state === "TRIPPED")
    return { ready: false, reason: "设备保护已触发，请在控制台确认安全后恢复" };
  if (!connected || !frame || !Number.isFinite(frameAgeMs) ||
      !Number.isFinite(statusAgeMs) || frameAgeMs >= 1000 || statusAgeMs >= 3000)
    return { ready: false, reason: "等待设备数据更新" };
  if (status.body !== "real")
    return { ready: false, reason: "尚未确认连接到实际设备" };
  if (!(["table", "wearing"].includes(status.profile)))
    return { ready: false, reason: "等待确认设备使用方式" };
  if (status.state !== "ARMED" || status.legs_offline || status.tripped ||
      !Number.isFinite(status.hz) || status.hz < 50)
    return { ready: false, reason: "设备尚未就绪" };
  if (!confirmed)
    return { ready: false, reason: "请先确认设备当前使用方式" };
  return { ready: true, reason: "设备已就绪" };
}

export function connectTelemetry({ onChange, WebSocketClass = WebSocket, now = () => performance.now() }) {
  let socket = null;
  let reconnectTimer = null;
  let monitorTimer = null;
  let closed = false;
  let connected = false;
  let status = {};
  let frame = null;
  let frameAt = -Infinity;
  let statusAt = -Infinity;

  const emit = () => {
    const state = liveState(status, frame, now() - frameAt, connected);
    onChange({ ...state, status, frame: state.usable ? frame : null,
      connected, frameAgeMs: now() - frameAt, statusAgeMs: now() - statusAt });
  };

  const connect = () => {
    if (closed) return;
    socket = new WebSocketClass("ws://127.0.0.1:8765");
    socket.onopen = () => {
      connected = true;
      emit();
    };
    socket.onmessage = (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.k === "st") {
        status = message;
        statusAt = now();
        emit();
      } else if (message.k === "s") {
        const parsed = parseFrame(message);
        if (!parsed) return;
        frameAt = now();
        frame = { ...parsed, receivedAt: frameAt };
        emit();
      }
    };
    socket.onclose = () => {
      connected = false;
      frame = null;
      frameAt = -Infinity;
      status = {};
      statusAt = -Infinity;
      emit();
      if (!closed) reconnectTimer = setTimeout(connect, RETRY_MS);
    };
    socket.onerror = () => socket.close();
  };

  connect();
  monitorTimer = setInterval(emit, 250);
  emit();
  const close = () => {
    closed = true;
    clearTimeout(reconnectTimer);
    clearInterval(monitorTimer);
    socket?.close();
  };
  close.send = (command) => {
    if (closed || !connected || socket?.readyState !== WebSocketClass.OPEN)
      throw new Error("设备连接已断开");
    socket.send(JSON.stringify(command));
  };
  return close;
}
