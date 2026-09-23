import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const viewport = document.getElementById("twin-viewport");
const loadButton = document.getElementById("load-model");
const replayButton = document.getElementById("replay-toggle");
const poster = document.getElementById("twin-poster");
const errorEl = document.getElementById("twin-error");
const leftEl = document.getElementById("left-angle");
const rightEl = document.getElementById("right-angle");

let viewer;
let replay;
let playing = false;
let elapsed = 0;
let previous = 0;
let neutral;

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

function showFrame(frame) {
  if (!viewer || !frame) return;
  const left = frame[4];
  const right = frame[5];
  if (!neutral) neutral = { left, right };
  leftEl.textContent = `${left.toFixed(1)}°`;
  rightEl.textContent = `${right.toFixed(1)}°`;
  if (viewer.left && viewer.right) {
    const axis = viewer.config.axis || "z";
    viewer.left.rotation[axis] =
      (((left - neutral.left) * Math.PI) / 180) * viewer.config.sign.left;
    viewer.right.rotation[axis] =
      (((right - neutral.right) * Math.PI) / 180) * viewer.config.sign.right;
  }
}

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
    showFrame(frames[low]);
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
      fetch("data/twin-config.json"),
      fetch("data/twin-replay.json"),
    ]);
    if (!configResponse.ok || !replayResponse.ok)
      throw new Error("展示数据暂时不可用");
    const config = await configResponse.json();
    replay = await replayResponse.json();
    const gltf = await new GLTFLoader().loadAsync("assets/exoskeleton.glb");
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
    const left = attachPart(root, config.left);
    const right = attachPart(root, config.right);
    const bounds = new THREE.Box3().setFromObject(root);
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    root.position.sub(center);
    const holder = new THREE.Group();
    holder.add(root);
    holder.scale.setScalar(2.5 / Math.max(size.x, size.y, size.z, 0.01));
    scene.add(holder);
    const sphere = new THREE.Box3()
      .setFromObject(holder)
      .getBoundingSphere(new THREE.Sphere());
    const distance =
      (sphere.radius / Math.sin((camera.fov * Math.PI) / 360)) * 1.25;
    camera.position.set(distance * 0.48, distance * 0.32, distance * 0.8);
    camera.lookAt(0, 0, 0);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.minDistance = 1;
    controls.maxDistance = 40;
    viewer = { scene, camera, renderer, controls, config, left, right };
    viewport.appendChild(renderer.domElement);
    poster.hidden = true;
    loadButton.hidden = true;
    replayButton.disabled = false;
    showFrame(replay.frames[0]);
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
