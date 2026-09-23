import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { connectTelemetry } from "./live.js";
import { modeReadiness, modeCommand } from "./control.js";
import { GaitPatternDetector, YawFollower } from "./motion.js";

const viewport = document.getElementById("twin-viewport");
const loadButton = document.getElementById("load-model");
const replayButton = document.getElementById("replay-toggle");
const poster = document.getElementById("twin-poster");
const errorEl = document.getElementById("twin-error");
const leftEl = document.getElementById("left-angle");
const rightEl = document.getElementById("right-angle");
const liveButton = document.getElementById("mode-live");
const replayModeButton = document.getElementById("mode-replay");
const humanButton = document.getElementById("human-toggle");
const alignButton = document.getElementById("align-pose");
const turnButton = document.getElementById("turn-toggle");
const sourceEl = document.getElementById("source-label");
const stateEl = document.getElementById("device-state");
const leftSpeedEl = document.getElementById("left-speed");
const rightSpeedEl = document.getElementById("right-speed");
const leftTorqueEl = document.getElementById("left-torque");
const rightTorqueEl = document.getElementById("right-torque");
const rateEl = document.getElementById("frame-rate");
const gaitEl = document.getElementById("gait-state");
const assistButton = document.getElementById("start-assist");
const resistButton = document.getElementById("start-resist");
const zeroButton = document.getElementById("control-zero");
const estopButton = document.getElementById("control-estop");
const controlConfirm = document.getElementById("control-confirm");
const confirmLabel = document.getElementById("control-confirm-label");
const controlReason = document.getElementById("control-reason");
const controlCurrent = document.getElementById("control-current");

let viewer;
let replay;
let mode = "live";
let live = { label: "正在检查连接", level: "offline", frame: null, status: {} };
let playing = false;
let elapsed = 0;
let previous = 0;
let neutral = { live: null, replay: null };
let humanVisible = true;
let liveRefreshScheduled = false;
let turnEnabled = true;
let confirmedProfile = null;
const yawFollower = new YawFollower();
const gaitDetector = new GaitPatternDetector();

function attachPart(root, spec) {
  if (!spec || !Array.isArray(spec.names) || !Array.isArray(spec.pivot))
    return null;
  const nodes = spec.names.map((name) => root.getObjectByName(name));
  if (nodes.some((node) => !node)) return null;
  const pivot = new THREE.Group();
  pivot.position.fromArray(spec.pivot);
  root.add(pivot);
  root.updateMatrixWorld(true);
  for (const node of nodes) pivot.attach(node);
  return pivot;
}

function fitAssembly(parent, names, pivot, scale, offset = [0, 0, 0]) {
  const nodes = names.map((name) => parent.getObjectByName(name));
  if (nodes.some((node) => !node)) throw new Error("外骨骼模型缺少固定件");
  const mount = new THREE.Group();
  mount.position.fromArray(pivot);
  parent.add(mount);
  parent.updateMatrixWorld(true);
  for (const node of nodes) mount.attach(node);
  mount.scale.fromArray(scale);
  mount.position.add(new THREE.Vector3().fromArray(offset));
  return mount;
}

function taperSupportToCuff(root, name, cuff) {
  const bar = root.getObjectByName(name);
  if (!bar?.isMesh) throw new Error("外骨骼模型缺少腿部支撑杆");
  root.updateMatrixWorld(true);
  bar.updateWorldMatrix(true, false);
  const toRoot = new THREE.Matrix4().copy(root.matrixWorld).invert()
    .multiply(bar.matrixWorld);
  const toMesh = toRoot.clone().invert();
  const geometry = bar.geometry.clone();
  const positions = geometry.getAttribute("position");
  const point = new THREE.Vector3();
  for (let index = 0; index < positions.count; index += 1) {
    point.fromBufferAttribute(positions, index).applyMatrix4(toRoot);
    // The hip end stays fixed; the knee end lands at the resized cuff.
    const t = THREE.MathUtils.clamp((0.12 - point.y) / 0.37, 0, 1);
    const weight = t * t * (3 - 2 * t);
    point.x += weight * (
      cuff.pivot[0] + cuff.offset[0]
      + (point.x - cuff.pivot[0]) * cuff.scale[0] - point.x
    );
    point.y += weight * cuff.offset[1];
    point.z += weight * (
      cuff.pivot[2]
      + (point.z - cuff.pivot[2]) * cuff.scale[2] - point.z
    );
    point.applyMatrix4(toMesh);
    positions.setXYZ(index, point.x, point.y, point.z);
  }
  positions.needsUpdate = true;
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  bar.geometry = geometry;
}

function fitWornParts(root, left, right, config) {
  const { waist, leftCuff, rightCuff } = config.fit;
  fitAssembly(root, waist.names, waist.pivot, waist.scale);
  for (const [leg, cuff, hip] of [
    [left, leftCuff, config.left.pivot],
    [right, rightCuff, config.right.pivot],
  ]) {
    if (!leg) continue;
    const localPivot = cuff.pivot.map((value, index) => value - hip[index]);
    fitAssembly(leg, cuff.names, localPivot, cuff.scale, cuff.offset);
  }
}

function makeJointPose(joint) {
  if (!joint) return null;
  joint.parent.updateWorldMatrix(true, false);
  const parentRotation = joint.parent.getWorldQuaternion(new THREE.Quaternion());
  return {
    joint,
    rest: joint.quaternion.clone(),
    axis: new THREE.Vector3(0, 0, 1).applyQuaternion(parentRotation.invert()),
  };
}

function poseJoint(spec, radians) {
  if (!spec) return;
  spec.joint.quaternion.copy(spec.rest).premultiply(
    new THREE.Quaternion().setFromAxisAngle(spec.axis, radians),
  );
}

function createHuman(gltf, holder, center) {
  const root = gltf.scene;
  // GLTFLoader removes ':' from Mixamo bone names for animation bindings.
  const hips = root.getObjectByName("mixamorigHips");
  const leftHip = root.getObjectByName("mixamorigLeftUpLeg");
  const rightHip = root.getObjectByName("mixamorigRightUpLeg");
  if (!hips || !leftHip || !rightHip)
    throw new Error("人体模型缺少髋部骨骼");
  root.scale.setScalar(2.4);
  // The generated character faces the opposite way from the worn exoskeleton.
  root.rotation.y = Math.PI;
  root.updateMatrixWorld(true);
  const hipPosition = hips.getWorldPosition(new THREE.Vector3());
  root.position.set(
    -center.x - 0.03 - hipPosition.x,
    0.18 - center.y - hipPosition.y,
    -center.z - hipPosition.z,
  );
  root.traverse((object) => {
    if (!object.isMesh) return;
    const makeGlass = (material) => {
      const glass = material.clone();
      // Keep the smooth silhouette and rig, but hide facial and clothing detail.
      glass.map = null;
      glass.normalMap = null;
      glass.roughnessMap = null;
      glass.metalnessMap = null;
      glass.emissiveMap = null;
      glass.aoMap = null;
      glass.vertexColors = false;
      glass.color.set(0xf5f8f5);
      glass.metalness = 0;
      glass.roughness = 0.92;
      glass.transparent = true;
      glass.opacity = 0.58;
      glass.depthWrite = false;
      glass.side = THREE.DoubleSide;
      return glass;
    };
    object.material = Array.isArray(object.material)
      ? object.material.map(makeGlass) : makeGlass(object.material);
    object.frustumCulled = false;
    object.renderOrder = -1;
  });
  holder.add(root);
  root.updateMatrixWorld(true);
  return {
    root,
    // Preserve the mannequin's anatomical sides after the half turn.
    left: makeJointPose(leftHip),
    right: makeJointPose(rightHip),
  };
}

function showFrame(frame, source) {
  if (!frame) return;
  if (source === "live") {
    yawFollower.update(frame);
    gaitEl.textContent = gaitDetector.update(frame)
      ? "检测到交替摆腿" : "未检测到交替摆腿";
  } else {
    gaitEl.textContent = "桌面记录";
  }
  const { left, right } = frame;
  if (!neutral[source]) neutral[source] = { left, right };
  leftEl.textContent = `${left.toFixed(1)}°`;
  rightEl.textContent = `${right.toFixed(1)}°`;
  leftSpeedEl.textContent = `${frame.leftSpeed.toFixed(1)} °/s`;
  rightSpeedEl.textContent = `${frame.rightSpeed.toFixed(1)} °/s`;
  leftTorqueEl.textContent = `${frame.leftTorque.toFixed(2)} N·m`;
  rightTorqueEl.textContent = `${frame.rightTorque.toFixed(2)} N·m`;
  if (!viewer) return;
  viewer.holder.rotation.y = source === "live" && turnEnabled
    ? yawFollower.angle * Math.PI / 180 : 0;
  if (viewer.left && viewer.right) {
    const axis = viewer.config.axis || "z";
    const leftRotation =
      (((left - neutral[source].left) * Math.PI) / 180) * viewer.config.sign.left;
    const rightRotation =
      (((right - neutral[source].right) * Math.PI) / 180) * viewer.config.sign.right;
    viewer.left.rotation[axis] = leftRotation;
    viewer.right.rotation[axis] = rightRotation;
    poseJoint(viewer.human?.left, leftRotation);
    poseJoint(viewer.human?.right, rightRotation);
  }
}

function replayFrame(row) {
  return {
    left: row[4], right: row[5], leftSpeed: row[6], rightSpeed: row[7],
    leftTorque: row[8], rightTorque: row[9],
  };
}

function clearReadings() {
  for (const element of [leftEl, rightEl, leftSpeedEl, rightSpeedEl, leftTorqueEl, rightTorqueEl, rateEl])
    element.textContent = "—";
}

function updateMode() {
  const isLive = mode === "live";
  liveButton.classList.toggle("active", isLive);
  replayModeButton.classList.toggle("active", !isLive);
  liveButton.setAttribute("aria-pressed", String(isLive));
  replayModeButton.setAttribute("aria-pressed", String(!isLive));
  replayButton.hidden = isLive;
  alignButton.hidden = !isLive;
  alignButton.disabled = !viewer || !live.frame;
  turnButton.hidden = !isLive;
  turnButton.disabled = !viewer || !live.frame;
  if (isLive) {
    stateEl.textContent = live.label;
    stateEl.dataset.level = live.level;
    sourceEl.textContent = live.frame
      ? live.status.body === "real" ? "真机实时数据" : "实时数据 · 来源未标记"
      : "等待真机数据";
    if (live.frame) {
      showFrame(live.frame, "live");
      rateEl.textContent = Number.isFinite(live.status.hz)
        ? `${live.status.hz.toFixed(0)} Hz` : "—";
    } else {
      gaitDetector.clear();
      gaitEl.textContent = "—";
      clearReadings();
    }
  } else {
    gaitDetector.clear();
    gaitEl.textContent = "桌面记录";
    stateEl.textContent = "桌面标定记录";
    stateEl.dataset.level = "warn";
    sourceEl.textContent = "历史桌面实测记录";
    rateEl.textContent = "—";
    if (replay?.frames?.length) showFrame(replayFrame(replay.frames[0]), "replay");
    else clearReadings();
  }
  updateControls();
}

function updateControls() {
  const profile = live.status?.profile;
  const canConfirm = live.connected && live.status?.body === "real" &&
    ["table", "wearing"].includes(profile);
  if (!canConfirm || (confirmedProfile && confirmedProfile !== profile)) {
    confirmedProfile = null;
    controlConfirm.checked = false;
  }
  controlConfirm.disabled = !canConfirm;
  confirmLabel.textContent = profile === "table"
    ? "我确认设备放在桌面或支架上、无人穿戴（桌面档）"
    : profile === "wearing"
      ? "我确认当前有人穿戴，已按穿戴档完成检查并能立即急停"
      : "等待设备报告安全档";
  const ready = modeReadiness(live, confirmedProfile);
  assistButton.disabled = resistButton.disabled = mode !== "live" || !ready.ready;
  zeroButton.disabled = estopButton.disabled = !live.connected;
  const names = { zero: "松劲", assist: "动力辅助", resist: "健身阻力" };
  controlCurrent.textContent = live.connected && live.statusAgeMs < 3000 && live.status?.policy
    ? `当前模式：${names[live.status.policy] || live.status.policy}` : "当前模式：等待设备";
  controlReason.textContent = mode === "live" ? ready.reason : "切换到实时数据后可操作";
}

controlConfirm.addEventListener("change", () => {
  confirmedProfile = controlConfirm.checked ? live.status?.profile : null;
  updateControls();
});

function sendMode(name) {
  try {
    const readiness = modeReadiness(live, confirmedProfile);
    if (mode !== "live") throw new Error("请先切换到实时数据");
    telemetry.send(modeCommand(name, readiness));
    controlReason.textContent = "请求已发送，等待设备状态确认";
  } catch (error) {
    controlReason.textContent = error.message;
  }
}

assistButton.addEventListener("click", () => sendMode("assist"));
resistButton.addEventListener("click", () => sendMode("resist"));
zeroButton.addEventListener("click", () => {
  try { telemetry.send({ op: "zero" }); controlReason.textContent = "松劲请求已发送"; }
  catch (error) { controlReason.textContent = error.message; }
});
estopButton.addEventListener("click", () => {
  try { telemetry.send({ op: "estop" }); controlReason.textContent = "急停请求已发送"; }
  catch (error) { controlReason.textContent = error.message; }
});

const telemetry = connectTelemetry({ onChange: (next) => {
  live = next;
  updateControls();
  if (mode !== "live" || liveRefreshScheduled) return;
  liveRefreshScheduled = true;
  requestAnimationFrame(() => {
    liveRefreshScheduled = false;
    if (mode === "live") updateMode();
  });
} });

function render(now) {
  if (!viewer) return;
  const delta = Math.min((now - previous) / 1000, 0.1);
  previous = now;
  if (playing && replay?.frames?.length) {
    const frames = replay.frames;
    const duration = frames[frames.length - 1][0];
    elapsed = (elapsed + delta) % duration;
    let low = 0;
    let high = frames.length - 1;
    while (low < high) {
      const mid = (low + high) >>> 1;
      if (frames[mid][0] < elapsed) low = mid + 1;
      else high = mid;
    }
    showFrame(replayFrame(frames[low]), "replay");
  }
  viewer.controls.update();
  viewer.renderer.render(viewer.scene, viewer.camera);
  requestAnimationFrame(render);
}

function resize() {
  if (!viewer) return;
  const { width, height } = viewport.getBoundingClientRect();
  viewer.camera.aspect = width / height;
  viewer.camera.updateProjectionMatrix();
  viewer.renderer.setSize(width, height, false);
}

async function startViewer() {
  loadButton.disabled = true;
  loadButton.textContent = "正在载入 3D 视图…";
  errorEl.hidden = true;
  try {
    const [configResponse, replayResponse] = await Promise.all([
      fetch("data/twin-config.json", { cache: "no-store" }),
      fetch("data/twin-replay.json"),
    ]);
    if (!configResponse.ok || !replayResponse.ok)
      throw new Error("展示数据暂时不可用");
    const config = await configResponse.json();
    if (!Number.isFinite(config.upright?.left) || !Number.isFinite(config.upright?.right))
      throw new Error("直立基准配置无效");
    neutral.live = { ...config.upright };
    replay = await replayResponse.json();
    const loader = new GLTFLoader();
    const [gltf, humanGltf] = await Promise.all([
      loader.loadAsync("assets/exoskeleton.glb"),
      loader.loadAsync("assets/human-tripo-rigged.glb"),
    ]);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.6;
    scene.add(new THREE.HemisphereLight(0xe6f1dc, 0x263026, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 2.7);
    key.position.set(2, 4, 3);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xb6db7e, 2);
    rim.position.set(-3, 2, -2);
    scene.add(rim);

    const root = gltf.scene;
    // Keep framing anchored to the source asset. Fitted cuffs must not
    // rescale or recenter the whole person when their height changes.
    const sourceBounds = new THREE.Box3().setFromObject(root);
    const center = sourceBounds.getCenter(new THREE.Vector3());
    const size = sourceBounds.getSize(new THREE.Vector3());
    taperSupportToCuff(root, "tripo_part_3", config.fit.leftCuff);
    taperSupportToCuff(root, "tripo_part_5", config.fit.rightCuff);
    const left = attachPart(root, config.left);
    const right = attachPart(root, config.right);
    fitWornParts(root, left, right, config);
    root.position.sub(center);
    const holder = new THREE.Group();
    holder.add(root);
    holder.scale.setScalar(2.5 / Math.max(size.x, size.y, size.z, 0.01));
    const sphere = sourceBounds.getBoundingSphere(new THREE.Sphere());
    sphere.radius *= holder.scale.x;
    const human = createHuman(humanGltf, holder, center);
    human.root.visible = humanVisible;
    scene.add(holder);
    const distance =
      (sphere.radius / Math.sin((camera.fov * Math.PI) / 360)) * 1.95;
    camera.position.set(distance * 0.75, distance * 0.28, distance * 0.65);
    camera.lookAt(0, 0.2, 0);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.minDistance = 1;
    controls.maxDistance = 40;
    controls.target.set(0, 0.2, 0);
    // The Tripo exoskeleton's +Z group is named `right` in the asset config,
    // but it lies beside the mannequin's anatomical left hip after rotation.
    // Map the left sensor to both +Z parts, and the right sensor to both -Z parts.
    viewer = { scene, camera, renderer, controls, config,
      left: right, right: left, human, holder };
    viewport.appendChild(renderer.domElement);
    poster.hidden = true;
    loadButton.hidden = true;
    replayButton.disabled = false;
    humanButton.disabled = false;
    updateMode();
    resize();
    window.addEventListener("resize", resize);
    previous = performance.now();
    requestAnimationFrame(render);
  } catch (error) {
    loadButton.disabled = false;
    loadButton.innerHTML = "重试 3D 视图 <span>↗</span>";
    errorEl.textContent =
      error instanceof Error ? error.message : "3D 视图暂时不可用";
    errorEl.hidden = false;
  }
}

loadButton.addEventListener("click", startViewer);
// The local live view is ready before the device powers on; fresh frames drive it on arrival.
startViewer();
liveButton.addEventListener("click", () => {
  mode = "live";
  playing = false;
  replayButton.innerHTML = "播放记录 <span>▶</span>";
  updateMode();
});
replayModeButton.addEventListener("click", () => {
  mode = "replay";
  updateMode();
});
humanButton.addEventListener("click", () => {
  humanVisible = !humanVisible;
  if (viewer?.human) viewer.human.root.visible = humanVisible;
  humanButton.setAttribute("aria-pressed", String(humanVisible));
  humanButton.textContent = `半透明人体：${humanVisible ? "显示" : "隐藏"}`;
});
alignButton.addEventListener("click", () => {
  if (!viewer || !live.frame || mode !== "live") return;
  yawFollower.align(live.frame.yaw, live.frame.receivedAt);
  showFrame(live.frame, "live");
});
turnButton.addEventListener("click", () => {
  turnEnabled = !turnEnabled;
  if (turnEnabled && live.frame) yawFollower.align(live.frame.yaw, live.frame.receivedAt);
  if (viewer?.holder) viewer.holder.rotation.y = 0;
  turnButton.setAttribute("aria-pressed", String(turnEnabled));
  turnButton.textContent = `转身跟随：${turnEnabled ? "开" : "关"}`;
});
replayButton.addEventListener("click", () => {
  playing = !playing;
  replayButton.innerHTML = playing
    ? "暂停记录 <span>Ⅱ</span>"
    : "播放记录 <span>▶</span>";
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && playing) {
    playing = false;
    replayButton.innerHTML = "播放记录 <span>▶</span>";
  }
});
