// The exoskeleton measures hips, not knees. This is a visual pose estimate for
// the mannequin only; it must never be used as a measured joint angle.
export function forwardHipDegrees(modelHipRadians) {
  return -modelHipRadians * 180 / Math.PI;
}

export function kneeFlexTarget(modelHipRadians) {
  if (!Number.isFinite(modelHipRadians)) return 0;
  const forward = forwardHipDegrees(modelHipRadians);
  // Ignore small differences around the previously recorded upright pose.
  // Above that range, bend the shin backward relative to the thigh. The
  // extra flex compensates for this model's slightly forward-leaning shins.
  const lift = Math.max(0, forward - 4);
  return Math.min(135, 1.5 * lift + 6 * (1 - Math.exp(-lift / 4)));
}

export class KneePose {
  constructor() { this.reset(); }

  reset() {
    this.left = 0;
    this.right = 0;
    this.leftTarget = 0;
    this.rightTarget = 0;
    this.lastAt = null;
  }

  setHipRotations(leftRadians, rightRadians) {
    this.leftTarget = kneeFlexTarget(leftRadians);
    this.rightTarget = kneeFlexTarget(rightRadians);
  }

  step(at) {
    if (!Number.isFinite(at)) return { left: this.left, right: this.right };
    const elapsed = this.lastAt === null ? 0 : Math.max(0, Math.min((at - this.lastAt) / 1000, 0.1));
    const blend = 1 - Math.exp(-elapsed / 0.16);
    this.left += blend * (this.leftTarget - this.left);
    this.right += blend * (this.rightTarget - this.right);
    this.lastAt = at;
    return { left: this.left, right: this.right };
  }
}
