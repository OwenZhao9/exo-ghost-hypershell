import assert from "node:assert/strict";
import test from "node:test";
import { liveState, parseFrame } from "../site/live.js";
import { GaitPatternDetector, YawFollower } from "../site/motion.js";

const sensor = { k: "s", v: [-12, 23, 1.5, -2.5, 0.1, -0.2, 0, 10, 11, 12] };

test("maps the live sensor fields used by the 3D view", () => {
  assert.deepEqual(parseFrame(sensor), {
    left: -12, right: 23, leftSpeed: 1.5, rightSpeed: -2.5,
    leftTorque: 0.1, rightTorque: -0.2, pitch: 10, roll: 11, yaw: 12,
    gx: null, gy: null, gz: null,
  });
  assert.equal(parseFrame({ k: "s", v: [1] }), null);
  assert.equal(parseFrame({ ...sensor, v: [NaN, ...sensor.v.slice(1)] }), null);
});

test("relative turn follows measured rotation but ignores stationary yaw drift and wrap jumps", () => {
  const follower = new YawFollower();
  const frame = (yaw, gz, receivedAt) => ({ yaw, gx: 0, gy: 0, gz, receivedAt });
  assert.equal(follower.update(frame(179, 0, 0)), 0);
  assert.equal(follower.update(frame(-179, 8, 20)), 2);
  assert.equal(follower.update(frame(-178.5, 0.5, 40)), 2);
  assert.equal(follower.update(frame(-160, 8, 60)), 2); // implausible one-frame jump
  assert.equal(follower.update(frame(-150, 8, 1000)), 2); // reconnect gap
  follower.align(-150, 1000);
  assert.equal(follower.update(frame(-147, 8, 1020)), 3);
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

test("bilateral alternating hip motion is detected without claiming one-leg movement as gait", () => {
  const gait = new GaitPatternDetector();
  for (let at = 0; at <= 4000; at += 50) {
    const swing = Math.sin((at / 1000) * 2 * Math.PI);
    gait.update({ receivedAt: at, left: -30 + 12 * swing, right: 35 + 10 * swing });
  }
  assert.equal(gait.active, true);
  gait.clear();
  for (let at = 0; at <= 4000; at += 50) {
    gait.update({ receivedAt: at, left: -30 + 12 * Math.sin((at / 1000) * 2 * Math.PI), right: 35 });
  }
  assert.equal(gait.active, false);
  gait.clear();
  assert.equal(gait.update({ receivedAt: 0, left: -30, right: 35 }), false);
  assert.equal(gait.update({ receivedAt: 1000, left: -18, right: 45 }), false);
});
