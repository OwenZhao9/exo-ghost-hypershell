export function signedAngleDifference(current, previous) {
  return ((current - previous + 540) % 360) - 180;
}

// The waist IMU yaw drifts while stationary. Accept only short yaw changes
// accompanied by measurable gyro motion; this is a relative heading display.
export class YawFollower {
  constructor() {
    this.angle = 0;
    this.lastYaw = null;
    this.lastAt = null;
  }

  align(yaw, at) {
    this.angle = 0;
    this.lastYaw = yaw;
    this.lastAt = at;
  }

  update(frame) {
    const { yaw, gx, gy, gz, receivedAt } = frame;
    if (!Number.isFinite(yaw) || !Number.isFinite(receivedAt)) return this.angle;
    if (this.lastYaw === null) {
      this.align(yaw, receivedAt);
      return this.angle;
    }
    if (receivedAt === this.lastAt) return this.angle;
    const elapsed = receivedAt - this.lastAt;
    const change = signedAngleDifference(yaw, this.lastYaw);
    this.lastYaw = yaw;
    this.lastAt = receivedAt;
    const gyroSpeed = Math.hypot(gx, gy, gz);
    if (elapsed > 0 && elapsed < 500 && Math.abs(change) < 15 &&
        Number.isFinite(gyroSpeed) && gyroSpeed >= 4) {
      this.angle += change;
    }
    return this.angle;
  }
}

// Raw left/right angles have mirrored hardware signs: alternating physical
// legs produce broadly in-phase traces. This detects the pattern, not steps,
// foot contact, distance, or proof that a person is wearing the device.
export class GaitPatternDetector {
  constructor() {
    this.points = [];
    this.lastAt = null;
    this.active = false;
  }

  clear() {
    this.points = [];
    this.lastAt = null;
    this.active = false;
  }

  update(frame) {
    const at = frame.receivedAt;
    if (![at, frame.left, frame.right].every(Number.isFinite)) return this.active;
    if (this.lastAt !== null && at - this.lastAt > 500) this.clear();
    if (this.lastAt !== null && at - this.lastAt < 40) return this.active;
    this.lastAt = at;
    this.points.push({ at, left: frame.left, right: frame.right });
    while (this.points.length && this.points[0].at < at - 3500) this.points.shift();
    const points = this.points;
    if (points.length < 30 || at - points[0].at < 2000) {
      this.active = false;
      return this.active;
    }

    const meanLeft = points.reduce((sum, point) => sum + point.left, 0) / points.length;
    const meanRight = points.reduce((sum, point) => sum + point.right, 0) / points.length;
    let varLeft = 0, varRight = 0, covariance = 0;
    let minLeft = Infinity, maxLeft = -Infinity, minRight = Infinity, maxRight = -Infinity;
    let previousSide = 0, crossings = 0;
    for (const point of points) {
      minLeft = Math.min(minLeft, point.left);
      maxLeft = Math.max(maxLeft, point.left);
      minRight = Math.min(minRight, point.right);
      maxRight = Math.max(maxRight, point.right);
      const left = point.left - meanLeft;
      const right = point.right - meanRight;
      varLeft += left * left;
      varRight += right * right;
      covariance += left * right;
      const side = left > 2 ? 1 : left < -2 ? -1 : 0;
      if (side && previousSide && side !== previousSide) crossings++;
      if (side) previousSide = side;
    }
    const correlation = covariance / Math.sqrt(varLeft * varRight || 1);
    this.active = maxLeft - minLeft >= 8 && maxRight - minRight >= 8 &&
      correlation >= 0.45 && crossings >= 3;
    return this.active;
  }
}
