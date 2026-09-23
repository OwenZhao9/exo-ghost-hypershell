import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const $ = id => document.getElementById(id);
const RAD = Math.PI / 180;
const F = { ldeg: 0, rdeg: 1, ldps: 2, rdps: 3, tl: 4, tr: 5,
  pitch: 7, roll: 8, yaw: 9 };
const host = location.hostname || 'localhost';
$('control-link').href = `http://${host}:8000/`;
const viewport = $('viewport');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 100);
camera.position.set(2.3, 1.5, 3.2);
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.6;
viewport.appendChild(renderer.domElement);
scene.add(new THREE.HemisphereLight(0xddefff, 0x25344a, 2.2));
const key = new THREE.DirectionalLight(0xffffff, 2.6);
key.position.set(2, 4, 3); scene.add(key);
const rim = new THREE.DirectionalLight(0x72adff, 2.0);
rim.position.set(-3, 2, -2); scene.add(rim);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.target.set(0, 0, 0);
controls.minDistance = 1.0;
controls.maxDistance = 40;

let mode = 'live';
let deviceState = 'OFFLINE';
let sourceMismatch = false;
let lastPose = null;
let lastPoseAt = 0;
let socket = null;
let socketToken = 0;
let replay = null;
let replayTime = 0;
let playing = true;
let lastFrameAt = performance.now();
let rig = null;
let neutral = null;

function setState(label, severity) {
  const el = $('device-state');
  el.textContent = label;
  el.className = `state ${severity || ''}`;
}

function showModelNote(message) {
  $('model-note').hidden = !message;
  if (message) $('model-note').textContent = message;
}

function numeric(id, value, decimals = 1, suffix = '') {
  $(id).textContent = Number.isFinite(value) ? `${value.toFixed(decimals)}${suffix}` : '—';
}

function updateMetrics(pose) {
  numeric('left-angle', pose?.ldeg, 1, '°');
  numeric('right-angle', pose?.rdeg, 1, '°');
  numeric('left-speed', pose?.ldps, 1, ' °/s');
  numeric('right-speed', pose?.rdps, 1, ' °/s');
  numeric('left-torque', pose?.tl, 2);
  numeric('right-torque', pose?.tr, 2);
  numeric('pitch', pose?.pitch);
  numeric('roll', pose?.roll);
  numeric('yaw', pose?.yaw);
}

function applyPose(pose) {
  updateMetrics(pose);
  if (!pose || !rig) return;
  if (!neutral) neutral = { ldeg: pose.ldeg, rdeg: pose.rdeg,
    pitch: pose.pitch, roll: pose.roll, yaw: pose.yaw };
  const { config, root, left, right } = rig;
  const sign = (mode === 'sim' && config.sim_sign) || config.sign || { left: -1, right: 1 };
  const axis = config.axis || 'z';
  left.rotation[axis] = (pose.ldeg - neutral.ldeg) * RAD * sign.left;
  right.rotation[axis] = (pose.rdeg - neutral.rdeg) * RAD * sign.right;
  if (config.use_imu) {
    root.rotation.set((pose.pitch - neutral.pitch) * RAD,
      (pose.yaw - neutral.yaw) * RAD, (pose.roll - neutral.roll) * RAD, 'YXZ');
  }
  $('pose-note').textContent = '双髋角度驱动 · 相对初始姿态';
}

function attachPart(root, spec) {
  const names = spec?.names || (spec?.name ? [spec.name] : []);
  if (!names.length || !Array.isArray(spec.pivot)) return null;
  const nodes = names.map(name => root.getObjectByName(name));
  if (nodes.some(node => !node)) return null;
  const pivot = new THREE.Group();
  pivot.position.fromArray(spec.pivot);
  root.add(pivot);
  root.updateMatrixWorld(true);
  for (const node of nodes) pivot.attach(node);
  return pivot;
}

async function loadModel() {
  let config;
  try {
    const response = await fetch('twin-config.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('模型配置不存在');
    config = await response.json();
    if (!config.model) throw new Error('还没有选定模型');
  } catch (_) {
    showModelNote('等待外骨骼 3D 模型确认。右侧数据和历史回放可先查看；3D 外形不会由程序臆造。');
    return;
  }
  try {
    const gltf = await new GLTFLoader().loadAsync(config.model);
    const root = gltf.scene;
    const left = attachPart(root, config.left);
    const right = attachPart(root, config.right);
    if (!left || !right) {
      showModelNote('已加载模型，但左右髋部件还未完成标定，暂不播放关节动作。');
    } else {
      showModelNote('');
    }
    const bounds = new THREE.Box3().setFromObject(root);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    root.position.sub(center);
    const holder = new THREE.Group();
    holder.add(root);
    holder.scale.setScalar(2.5 / Math.max(size.x, size.y, size.z, 0.01));
    scene.add(holder);
    const fitted = new THREE.Box3().setFromObject(holder);
    const sphere = fitted.getBoundingSphere(new THREE.Sphere());
    const distance = sphere.radius / Math.sin(camera.fov * RAD / 2) * 1.25;
    camera.position.set(distance * 0.48, distance * 0.32, distance * 0.8);
    camera.lookAt(0, 0, 0);
    controls.update();
    if (left && right) rig = { config, root: holder, left, right };
  } catch (error) {
    showModelNote(`模型加载失败：${error.message}`);
  }
}

function livePose(v) {
  return { ldeg: v[F.ldeg], rdeg: v[F.rdeg], ldps: v[F.ldps], rdps: v[F.rdps],
    tl: v[F.tl], tr: v[F.tr], pitch: v[F.pitch], roll: v[F.roll], yaw: v[F.yaw] };
}

function connect() {
  const selected = mode;
  if (selected === 'replay') return;
  const token = ++socketToken;
  socket?.close();
  const ws = new WebSocket(`ws://${host}:${selected === 'sim' ? 8766 : 8765}`);
  socket = ws;
  ws.onopen = () => {
    if (mode === selected) setState('数据通道已连接', 'warn');
  };
  ws.onmessage = event => {
    if (mode !== selected || token !== socketToken) return;
    let message;
    try { message = JSON.parse(event.data); } catch (_) { return; }
    if (message.k === 'st') {
      deviceState = message.state;
      sourceMismatch = Boolean(message.body && message.body !== (selected === 'sim' ? 'sim' : 'real'));
      $('frame-rate').textContent = `${Math.round(message.hz || 0)} Hz`;
      updateChannelState();
    } else if (message.k === 's' && Array.isArray(message.v)) {
      lastPose = livePose(message.v);
      lastPoseAt = performance.now();
      updateChannelState();
    }
  };
  ws.onclose = () => {
    if (token !== socketToken || mode !== selected) return;
    deviceState = 'OFFLINE';
    updateChannelState();
    setTimeout(() => {
      if (token === socketToken && mode === selected) connect();
    }, 1000);
  };
  ws.onerror = () => ws.close();
}

function updateChannelState() {
  const fresh = performance.now() - lastPoseAt < 1500;
  if (sourceMismatch) {
    setState('数据来源不匹配', 'bad');
    $('source-detail').textContent = '当前端口的数据来源与所选模式不一致，请检查服务端口。';
    $('pose-note').textContent = '模型停止更新';
    updateMetrics(null);
    return;
  }
  if (deviceState === 'LEGS_OFF') {
    setState('腿板无效', 'warn');
    $('source-detail').textContent = '串口仍可能有数据，但双髋关节传感器当前不可用。';
    $('pose-note').textContent = '关节数据无效 · 模型停止更新';
    updateMetrics(null);
    return;
  }
  if (deviceState === 'RECONN' || deviceState === 'OFFLINE' || !fresh) {
    setState(mode === 'sim' ? '等待仿真服务' : '等待外骨骼连接', 'bad');
    $('source-detail').textContent = mode === 'sim'
      ? '电脑仿真服务未连接。启动后模型将跟随模拟数据。'
      : '断线时模型保持最后有效姿态。';
    $('pose-note').textContent = '等待新的有效遥测';
    updateMetrics(null);
    return;
  }
  setState(deviceState === 'QUIET' ? '安全等待期' : mode === 'sim' ? '电脑仿真运行中' : '实时数据',
    deviceState === 'QUIET' ? 'warn' : 'ok');
  $('source-detail').textContent = mode === 'sim'
    ? '模型姿态跟随电脑仿真计算出的左右髋关节角度。'
    : '模型姿态跟随当前左右髋关节角度。';
  applyPose(lastPose);
}

async function loadReplay() {
  if (replay) return;
  const response = await fetch('twin-replay.json');
  if (!response.ok) throw new Error(`历史数据读取失败：${response.status}`);
  replay = await response.json();
}

function poseAt(t) {
  const frames = replay.frames;
  let lo = 0, hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid][0] <= t) lo = mid;
    else hi = mid - 1;
  }
  const a = frames[lo], b = frames[Math.min(lo + 1, frames.length - 1)];
  const fraction = b[0] > a[0] ? (t - a[0]) / (b[0] - a[0]) : 0;
  const p = a.map((value, i) => value + (b[i] - value) * fraction);
  return { ldeg: p[4], rdeg: p[5], ldps: p[6], rdps: p[7],
    tl: p[8], tr: p[9], pitch: p[1], roll: p[2], yaw: p[3] };
}

function updateReplay() {
  if (!replay) return;
  const end = replay.frames[replay.frames.length - 1][0];
  replayTime = Math.min(Math.max(replayTime, 0), end);
  $('timeline').value = String(Math.round(replayTime / end * 1000));
  $('play-time').textContent = `${replayTime.toFixed(1)} / ${end.toFixed(1)} s`;
  applyPose(poseAt(replayTime));
}

async function setMode(next) {
  if (next === 'replay') {
    try { await loadReplay(); }
    catch (error) { setState(error.message, 'bad'); return; }
  }
  if (mode === 'sim' && next !== 'sim' && socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ op: 'gait', name: null }));
  }
  mode = next;
  ++socketToken;
  socket?.close();
  socket = null;
  lastPose = null;
  lastPoseAt = 0;
  deviceState = 'OFFLINE';
  sourceMismatch = false;
  neutral = null;
  $('live-mode').classList.toggle('active', next === 'live');
  $('sim-mode').classList.toggle('active', next === 'sim');
  $('replay-mode').classList.toggle('active', next === 'replay');
  $('sim-controls').hidden = next !== 'sim';
  $('replay-controls').hidden = next !== 'replay';
  $('source-tag').textContent = next === 'live' ? '实时真机' : next === 'sim' ? '电脑仿真' : '历史录制回放';
  $('torque-title').textContent = next === 'live' ? '下发力矩' : next === 'sim' ? '模拟力矩' : '历史记录力矩';
  if (next === 'replay') {
    $('frame-rate').textContent = '录制数据';
    setState('历史录制回放', 'warn');
    $('source-detail').textContent = '2026-09-22 外骨骼实测记录；不会向设备下发命令。';
    updateReplay();
  } else {
    $('frame-rate').textContent = '— Hz';
    updateChannelState();
    connect();
  }
}

$('live-mode').onclick = () => setMode('live');
$('sim-mode').onclick = () => setMode('sim');
$('replay-mode').onclick = () => setMode('replay');
document.querySelectorAll('[data-gait]').forEach(button => {
  button.onclick = () => {
    if (mode !== 'sim' || sourceMismatch || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ op: 'gait', name: button.dataset.gait }));
    document.querySelectorAll('[data-gait]').forEach(item => item.classList.remove('active'));
    button.classList.add('active');
  };
});
$('play-pause').onclick = () => { playing = !playing; $('play-pause').textContent = playing ? '暂停' : '播放'; };
$('timeline').oninput = event => {
  if (!replay) return;
  const end = replay.frames[replay.frames.length - 1][0];
  replayTime = Number(event.target.value) / 1000 * end;
  updateReplay();
};

function animate(now) {
  requestAnimationFrame(animate);
  const dt = Math.min((now - lastFrameAt) / 1000, 0.1);
  lastFrameAt = now;
  if (mode === 'replay' && replay && playing) {
    replayTime += dt;
    if (replayTime >= replay.frames[replay.frames.length - 1][0]) replayTime = 0;
    updateReplay();
  }
  const width = viewport.clientWidth, height = viewport.clientHeight;
  if (width && height && (renderer.domElement.width !== Math.round(width * renderer.getPixelRatio()) ||
      renderer.domElement.height !== Math.round(height * renderer.getPixelRatio()))) {
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
  controls.update();
  renderer.render(scene, camera);
}

const launchOptions = new URLSearchParams(location.search);
if (launchOptions.get('embed') === '1') document.body.classList.add('embedded');
loadModel();
if (launchOptions.get('source') === 'replay') setMode('replay');
else connect();
requestAnimationFrame(animate);
