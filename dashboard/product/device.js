// A single browser connection to the existing controller. No device emulation.
export class Device extends EventTarget {
  constructor(config) {
    super(); this.config = config; this.status = null; this.sample = null;
    this.statusAt = 0; this.sampleAt = 0; this.history = []; this.closed = false;
    this.connect(); this.timer = setInterval(() => this.emit(), 500);
  }
  connect() {
    if (!this.config.device_ws || this.closed) return;
    const ws = this.ws = new WebSocket(this.config.device_ws);
    ws.onmessage = event => {
      let data; try { data = JSON.parse(event.data); } catch { return; }
      if (data.k === 'st') { this.status = data; this.statusAt = Date.now(); }
      if (data.k === 's' && Array.isArray(data.v) && data.v.length >= 7 &&
          data.v.slice(0, 7).every(Number.isFinite) && Number.isFinite(data.t)) {
        this.sample = data; this.sampleAt = Date.now(); this.history.push(data);
        if (this.history.length > 2400) this.history.splice(0, this.history.length - 2400);
      }
      this.emit();
    };
    ws.onclose = () => { this.status = null; this.sample = null; this.history = []; this.emit();
      if (!this.closed) this.retry = setTimeout(() => this.connect(), 1000); };
    ws.onerror = () => ws.close();
  }
  get fresh() { return this.ws?.readyState === WebSocket.OPEN && Date.now() - this.sampleAt < 1000 && Date.now() - this.statusAt < 3000; }
  get ready() { return this.fresh && this.status?.state === 'ARMED' && this.status?.body === 'real'; }
  send(command) {
    if (!this.config.control_enabled) throw new Error('当前页面用于查看，请在控制台操作设备');
    if (this.ws?.readyState !== WebSocket.OPEN) throw new Error('设备连接已断开');
    const stop = ['zero', 'estop'].includes(command.op);
    if (!stop && !this.ready) throw new Error('设备尚未就绪，请等待连接和安全检查完成');
    this.ws.send(JSON.stringify(command));
  }
  emit() { this.dispatchEvent(new Event('change')); }
  close() { this.closed = true; clearInterval(this.timer); clearTimeout(this.retry); this.ws?.close(); }
}
