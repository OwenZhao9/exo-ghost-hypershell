import { controlState } from "./live.js";

// Same first-use values as the product workspace. No automatic mode selection.
export const MODES = Object.freeze({
  assist: Object.freeze({ op: "policy", policy: "assist", gain: 0.1, max: 0.5 }),
  resist: Object.freeze({ op: "policy", policy: "resist", gain: 0.3, max: 0.5 }),
});

export function splitResistCommand(left, right, readiness, supported) {
  if (!readiness.ready) throw new Error(readiness.reason || "运动模式不可用");
  if (!supported) throw new Error("当前控制服务尚不支持左右独立阻力");
  if (![left, right].every((value) => Number.isFinite(value) && value >= 0 && value <= 0.5))
    throw new Error("左右阻力增益须在 0 到 0.5 之间");
  return { op: "policy", policy: "resist", gain: (left + right) / 2,
    gain_l: left, gain_r: right, max: 0.5 };
}

const LEG_GAIN_CAP = Object.freeze({ zero: 0, assist: 0.1, resist: 0.5 });

export function bilateralCommand(left, right, readiness, supported) {
  if (!readiness.ready) throw new Error(readiness.reason || "运动模式不可用");
  if (!supported) throw new Error("当前控制服务尚不支持左右独立助力与阻力");
  for (const leg of [left, right]) {
    if (!leg || !Object.hasOwn(LEG_GAIN_CAP, leg.mode) ||
        !Number.isFinite(leg.gain) || leg.gain < 0 || leg.gain > LEG_GAIN_CAP[leg.mode])
      throw new Error("助力增益不超过 0.1，阻力增益不超过 0.5，松劲增益为 0");
  }
  return { op: "policy", policy: "bilateral", gain: 0,
    mode_l: left.mode, gain_l: left.gain,
    mode_r: right.mode, gain_r: right.gain, max: 0.5 };
}

export function currentLegSetting(status, side) {
  if (status?.policy === "zero") return { mode: "zero", gain: 0 };
  if (status?.policy === "bilateral") {
    return { mode: status[`mode_${side}`], gain: status[`gain_${side}`] };
  }
  if (["assist", "resist"].includes(status?.policy)) {
    const sideGain = status[`gain_${side}`];
    return { mode: status.policy,
      gain: Number.isFinite(sideGain) ? sideGain : status.gain };
  }
  throw new Error("当前模式无法保留另一腿，请先松劲");
}

export function singleLegCommand(side, setting, status, readiness, supported) {
  if (!["l", "r"].includes(side)) throw new Error("腿侧无效");
  const other = currentLegSetting(status, side === "l" ? "r" : "l");
  return bilateralCommand(side === "l" ? setting : other,
    side === "r" ? setting : other, readiness, supported);
}

export function modeReadiness(live, confirmedProfile) {
  const profile = live.status?.profile;
  return controlState({
    status: live.status || {}, frame: live.frame,
    frameAgeMs: live.frameAgeMs, statusAgeMs: live.statusAgeMs,
    connected: live.connected, confirmed: confirmedProfile === profile,
  });
}

export function modeCommand(name, readiness) {
  if (!readiness.ready || !Object.hasOwn(MODES, name))
    throw new Error(readiness.reason || "运动模式不可用");
  return MODES[name];
}
