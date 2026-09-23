import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { Group, Object3D, PropertyBinding, Vector3 } from "../site/vendor/three.module.js";
import { kneeFlexRadians } from "../site/motion.js";

function loadHumanModel() {
  const bytes = readFileSync(new URL("../site/assets/human-tripo-rigged.glb", import.meta.url));
  assert.equal(bytes.toString("utf8", 0, 4), "glTF");
  const jsonLength = bytes.readUInt32LE(12);
  assert.equal(bytes.toString("utf8", 16, 20), "JSON");
  return JSON.parse(bytes.subarray(20, 20 + jsonLength).toString("utf8"));
}

test("the shipped Tripo human is skinned and exposes the hip and knee bones used by the viewer", () => {
  const model = loadHumanModel();
  assert.ok(model.skins?.length > 0);
  const names = new Set(model.nodes.map((node) => PropertyBinding.sanitizeNodeName(node.name || "")));
  for (const name of ["mixamorigHips", "mixamorigLeftUpLeg", "mixamorigRightUpLeg", "mixamorigLeftLeg", "mixamorigRightLeg"])
    assert.ok(names.has(name), `missing ${name}`);
});

test("estimated knee bend moves both ankles behind the shipped mannequin's toes", () => {
  const model = loadHumanModel();
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
  root.rotation.y = Math.PI; // Same front/back correction as createHuman().
  for (const index of model.scenes[model.scene || 0].nodes) root.add(objects[index]);
  root.updateMatrixWorld(true);
  for (const side of ["Left", "Right"]) {
    const bone = (part) => objects[model.nodes.findIndex((node) =>
      node.name === `mixamorig:${side}${part}`)];
    const knee = bone("Leg").getWorldPosition(new Vector3());
    const ankle = bone("Foot").getWorldPosition(new Vector3());
    const toe = bone("ToeBase").getWorldPosition(new Vector3());
    const shin = ankle.clone().sub(knee);
    const toeDirection = toe.clone().sub(ankle);
    const bentShin = shin.clone().applyAxisAngle(new Vector3(0, 0, 1), kneeFlexRadians(30));
    assert.ok(bentShin.sub(shin).dot(toeDirection) < 0,
      `${side} ankle must move opposite the toe-facing direction`);
  }
});
