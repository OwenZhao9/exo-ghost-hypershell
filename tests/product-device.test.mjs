import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../dashboard/product/device.js', import.meta.url), 'utf8');
const {Device} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

class Socket {
  static OPEN = 1;
  readyState = 1;
  sent = [];
  constructor() {}
  send(value) { this.sent.push(JSON.parse(value)); }
  receive(value) { this.onmessage({data: JSON.stringify(value)}); }
  close() { this.readyState = 3; this.onclose?.(); }
}
globalThis.WebSocket = Socket;

function connected(config = {}) {
  const d = new Device({device_ws: 'ws://test', control_enabled: true, ...config});
  d.ws.receive({k: 'st', state: 'ARMED', body: 'real', hz: 180});
  d.ws.receive({k: 's', t: 100, v: [1, 2, 3, 4, 0, 0, 1]});
  return d;
}

test('connection and stored preferences never send a control command', () => {
  const d = connected();
  try { assert.equal(d.ready, true); assert.deepEqual(d.ws.sent, []); }
  finally { d.close(); }
});

test('stale, non-real and read-only sources reject motion', () => {
  const command = {op: 'policy', policy: 'assist', gain: .1, max: .5};
  for (const kind of ['stale', 'sim', 'unknown', 'slow', 'read-only']) {
    const d = connected({control_enabled: kind !== 'read-only'});
    try {
      if (kind === 'stale') d.sampleAt -= 2000;
      if (kind === 'sim') d.status.body = 'sim';
      if (kind === 'unknown') delete d.status.body;
      if (kind === 'slow') d.status.hz = 3;
      assert.throws(() => d.send(command)); assert.deepEqual(d.ws.sent, []);
    } finally { d.close(); }
  }
});

test('explicit bounded policies work, unsafe motion does not, stop remains available', () => {
  const d = connected();
  try {
    d.send({op: 'policy', policy: 'assist', gain: .1, max: .5});
    for (const c of [{op: 'torque', L: 1}, {op: 'policy', policy: 'assist', gain: .5, max: 2},
                      {op: 'policy', policy: 'resist', gain: NaN, max: .5}]) assert.throws(() => d.send(c));
    d.sampleAt = 0; d.send({op: 'estop'});
    assert.equal(d.ws.sent.length, 2); assert.equal(d.ws.sent[1].op, 'estop');
  } finally { d.close(); }
  assert.equal(d.fresh, false); assert.deepEqual(d.history, []);
});

test('guide cue requires the separate bench flag, fresh real device and zero policy', () => {
  const d = connected({control_enabled: false, guide_motor_demo: true});
  try {
    d.status.profile = 'table'; d.status.policy = 'zero';
    d.send({op: 'guide_cue', direction: 'right', max: 9});
    assert.deepEqual(d.ws.sent[0], {op: 'guide_cue', direction: 'right'});
    d.status.policy = 'guide_cue';
    assert.throws(() => d.send({op: 'guide_cue', direction: 'left'}));
    d.status.policy = 'zero'; d.status.profile = 'wearing';
    assert.throws(() => d.send({op: 'guide_cue', direction: 'left'}));
    d.status.profile = 'table'; d.sampleAt = 0;
    assert.throws(() => d.send({op: 'guide_cue', direction: 'left'}));
    d.send({op: 'zero'});
    assert.deepEqual(d.ws.sent.at(-1), {op: 'zero'});
  } finally { d.close(); }
});
