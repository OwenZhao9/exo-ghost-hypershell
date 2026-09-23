import assert from "node:assert/strict";
import test from "node:test";
import { controlState, liveState, parseFrame } from "../site/live.js";
import { MODES, modeCommand, modeReadiness, splitResistCommand } from "../site/control.js";
import { GaitPatternDetector, KneeFollower, kneeFlexTarget, YawFollower } from "../site/motion.js";

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
  assert.deepEqual(liveState({ body: "real", state: "TRIPPED", legs_offline: true }, frame, 20, true), {
    label: "急停锁存 · 等待人工恢复", level: "warn", usable: false,
  });
});

test("mode controls require verified real source, profile and fresh armed data", () => {
  const base = { status: { body: "real", profile: "table", state: "ARMED", hz: 180 },
    frame: parseFrame(sensor), frameAgeMs: 20, statusAgeMs: 20,
    connected: true, confirmed: true };
  assert.equal(controlState(base).ready, true);
  assert.match(controlState({ ...base, frame: null,
    status: { ...base.status, state: "TRIPPED" } }).reason, /急停锁存/);
  for (const change of [
    { connected: false }, { frameAgeMs: 1000 }, { statusAgeMs: 3000 },
    { confirmed: false }, { status: { ...base.status, body: "sim" } },
    { status: { ...base.status, body: undefined } },
    { status: { ...base.status, profile: undefined } },
    { status: { ...base.status, state: "TRIPPED" } },
    { status: { ...base.status, hz: 20 } },
    { status: { ...base.status, hz: undefined } },
    { status: { ...base.status, legs_offline: true } },
  ]) assert.equal(controlState({ ...base, ...change }).ready, false);
  assert.equal(modeReadiness({ ...base, frame: base.frame }, "wearing").ready, false);
  assert.deepEqual(modeCommand("assist", { ready: true }), MODES.assist);
  assert.equal(MODES.assist.max, 0.5);
  assert.equal(MODES.resist.max, 0.5);
  assert.throws(() => modeCommand("assist", { ready: false, reason: "不就绪" }), /不就绪/);
  assert.deepEqual(splitResistCommand(0.3, 0.1, { ready: true }, true),
    { op: "policy", policy: "resist", gain: 0.2, gain_l: 0.3, gain_r: 0.1, max: 0.5 });
  assert.throws(() => splitResistCommand(0.3, 0.1, { ready: true }, false), /不支持/);
  assert.throws(() => splitResistCommand(0.6, 0.1, { ready: true }, true), /0.5/);
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

test("visual knee flex bends on forward lift, eases on lowering, and never invents measured motion", () => {
  assert.equal(kneeFlexTarget(0, 0), 0);
  assert.equal(kneeFlexTarget(-20, -80), 0);
  assert.ok(kneeFlexTarget(25, 60) > kneeFlexTarget(25, -60));
  assert.equal(kneeFlexTarget(100, 300), 65);
  const follower = new KneeFollower();
  let pose = follower.update({ leftHipDeg: 25, rightHipDeg: 0, leftSpeedDps: 60, rightSpeedDps: 0, at: 0 });
  assert.ok(pose.left > 0 && pose.left < 35);
  assert.equal(pose.right, 0);
  for (let at = 20; at <= 300; at += 20)
    pose = follower.update({ leftHipDeg: 25, rightHipDeg: 0, leftSpeedDps: 60, rightSpeedDps: 0, at });
  assert.ok(pose.left > 25);
  follower.clear();
  assert.deepEqual(follower.update({ leftHipDeg: 0, rightHipDeg: 0, leftSpeedDps: 0, rightSpeedDps: 0, at: 320 }), { left: 0, right: 0 });
});
