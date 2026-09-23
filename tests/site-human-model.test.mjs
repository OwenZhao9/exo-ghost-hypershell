import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { Group, Object3D, PropertyBinding, Vector3 } from "../site/vendor/three.module.js";
import { KneePose, kneeFlexTarget } from "../site/knee.js";

function loadModel() {
  const bytes = readFileSync(new URL("../site/assets/human-tripo-rigged.glb", import.meta.url));
  assert.equal(bytes.toString("utf8", 0, 4), "glTF");
  const jsonLength = bytes.readUInt32LE(12);
  assert.equal(bytes.toString("utf8", 16, 20), "JSON");
  return JSON.parse(bytes.subarray(20, 20 + jsonLength).toString("utf8"));
}

test("the shipped Tripo human is skinned and exposes independent hip and knee bones", () => {
  const model = loadModel();
  assert.ok(model.skins?.length > 0);
  const names = new Set(model.nodes.map((node) => PropertyBinding.sanitizeNodeName(node.name || "")));
  for (const name of ["mixamorigHips", "mixamorigLeftUpLeg", "mixamorigRightUpLeg",
    "mixamorigLeftLeg", "mixamorigRightLeg"])
    assert.ok(names.has(name), `missing ${name}`);
});

test("upright stays straight and forward lift folds each shin toward the heel", () => {
  const model = loadModel();
  const objects = model.nodes.map((node) => {
    const object = new Object3D();
    object.name = node.name || "";
    if (node.translation) object.position.fromArray(node.translation);
    if (node.rotation) object.quaternion.fromArray(node.rotation);
    if (node.scale) object.scale.fromArray(node.scale);
    return object;
  });
  model.nodes.forEach((node, index) => {
    for (const child of node.children || []) objects[index].add(objects[child]);
  });
  const root = new Group();
  root.rotation.y = Math.PI; // Same front/back correction as the live viewer.
  for (const index of model.scenes[model.scene || 0].nodes) root.add(objects[index]);
  root.updateMatrixWorld(true);
  assert.equal(kneeFlexTarget(-3.5 * Math.PI / 180), 0);
  for (const side of ["Left", "Right"]) {
    const bone = (part) => objects[model.nodes.findIndex((node) =>
      node.name === `mixamorig:${side}${part}`)];
    const knee = bone("Leg").getWorldPosition(new Vector3());
    const ankle = bone("Foot").getWorldPosition(new Vector3());
    const toe = bone("ToeBase").getWorldPosition(new Vector3());
    const shin = ankle.clone().sub(knee);
    const forward = toe.clone().sub(ankle).normalize();
    for (const lift of [15, 30, 60, 105]) {
      const flex = kneeFlexTarget(-lift * Math.PI / 180);
      const liftedShin = shin.clone().applyAxisAngle(new Vector3(0, 0, 1),
        (-lift + flex) * Math.PI / 180);
      assert.ok(liftedShin.dot(forward) < 0,
        `${side}: at ${lift}° hip lift, ankle must remain heelward of knee`);
    }
  }
});

test("knee pose eases toward the visual target and keeps both sides independent", () => {
  const pose = new KneePose();
  pose.setHipRotations(-30 * Math.PI / 180, 0);
  assert.deepEqual(pose.step(0), { left: 0, right: 0 });
  const moved = pose.step(160);
  assert.ok(moved.left > 0 && moved.left < kneeFlexTarget(-30 * Math.PI / 180));
  assert.equal(moved.right, 0);
  pose.reset();
  assert.deepEqual(pose.step(200), { left: 0, right: 0 });
});
