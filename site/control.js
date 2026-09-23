import { controlState } from "./live.js";

// Same first-use values as the product workspace. No automatic mode selection.
export const MODES = Object.freeze({
  assist: Object.freeze({ op: "policy", policy: "assist", gain: 0.1, max: 0.5 }),
  resist: Object.freeze({ op: "policy", policy: "resist", gain: 0.3, max: 0.5 }),
});

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
