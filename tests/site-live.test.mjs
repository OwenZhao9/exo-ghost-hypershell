import assert from "node:assert/strict";
import test from "node:test";
import { liveState, parseFrame } from "../site/live.js";

const sensor = { k: "s", v: [-12, 23, 1.5, -2.5, 0.1, -0.2, 0, 10, 11, 12] };

test("maps the live sensor fields used by the 3D view", () => {
  assert.deepEqual(parseFrame(sensor), {
    left: -12, right: 23, leftSpeed: 1.5, rightSpeed: -2.5,
    leftTorque: 0.1, rightTorque: -0.2, pitch: 10, roll: 11, yaw: 12,
  });
  assert.equal(parseFrame({ k: "s", v: [1] }), null);
  assert.equal(parseFrame({ ...sensor, v: [NaN, ...sensor.v.slice(1)] }), null);
});

test("never treats simulation, leg dropout, or stale samples as live movement", () => {
  const frame = parseFrame(sensor);
  assert.equal(liveState({ body: "sim" }, frame, 20, true).usable, false);
  assert.equal(liveState({ body: "real", legs_offline: true }, frame, 20, true).usable, false);
  assert.equal(liveState({ body: "real" }, frame, 1500, true).usable, false);
  assert.equal(liveState({ body: "real" }, frame, 20, false).usable, false);
  assert.equal(liveState({ body: "real", state: "ARMED" }, frame, 20, true).usable, true);
  assert.deepEqual(liveState({ body: "real", state: "TRIPPED" }, frame, 20, true), {
    label: "设备急停 · 实时读数", level: "warn", usable: true,
  });
});
