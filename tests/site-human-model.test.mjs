import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { Group, Object3D, PropertyBinding, Vector3 } from "../site/vendor/three.module.js";
import { forwardHipDegrees, kneeFlexRadians } from "../site/motion.js";

function loadHumanModel() {
  const bytes = readFileSync(new URL("../site/assets/human-tripo-rigged.glb", import.meta.url));
  assert.equal(bytes.toString("utf8", 0, 4), "glTF");
  const jsonLength = bytes.readUInt32LE(12);
  assert.equal(bytes.toString("utf8", 16, 20), "JSON");
  return { bytes, model: JSON.parse(bytes.subarray(20, 20 + jsonLength).toString("utf8")),
    binaryOffset: 20 + jsonLength + 8 };
}

test("the shipped Tripo human is skinned and exposes the hip and knee bones used by the viewer", () => {
  const { bytes, model, binaryOffset } = loadHumanModel();
  assert.ok(model.skins?.length > 0);
  const names = new Set(model.nodes.map((node) => PropertyBinding.sanitizeNodeName(node.name || "")));
  for (const name of ["mixamorigHips", "mixamorigLeftUpLeg", "mixamorigRightUpLeg", "mixamorigLeftLeg", "mixamorigRightLeg"])
    assert.ok(names.has(name), `missing ${name}`);
  const skin = model.skins[0];
  const skinnedNode = model.nodes.find((node) => node.skin === 0 && Number.isInteger(node.mesh));
  assert.ok(skinnedNode, "no mesh uses the rig");
  const attributes = model.meshes[skinnedNode.mesh].primitives[0].attributes;
  const joints = model.accessors[attributes.JOINTS_0];
  const weights = model.accessors[attributes.WEIGHTS_0];
  const start = (accessor) => binaryOffset +
    (model.bufferViews[accessor.bufferView].byteOffset || 0) + (accessor.byteOffset || 0);
  assert.equal(joints.count, weights.count);
  for (const side of ["Left", "Right"]) {
    const joint = skin.joints.findIndex((nodeIndex) =>
      model.nodes[nodeIndex].name === `mixamorig:${side}Leg`);
    let weightedVertices = 0;
    for (let vertex = 0; vertex < joints.count; vertex++) {
      for (let slot = 0; slot < 4; slot++) {
        if (bytes.readUInt8(start(joints) + vertex * 4 + slot) === joint &&
            bytes.readFloatLE(start(weights) + vertex * 16 + slot * 4) > 0.1) {
          weightedVertices++;
          break;
        }
      }
    }
    assert.ok(weightedVertices > 1000, `${side} shin has only ${weightedVertices} weighted vertices`);
  }
});

test("estimated knee bend moves both ankles behind the shipped mannequin's toes", () => {
  const { model } = loadHumanModel();
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
    const thigh = knee.clone().sub(bone("UpLeg").getWorldPosition(new Vector3()));
    const liftedThigh = thigh.clone().applyAxisAngle(new Vector3(0, 0, 1), -Math.PI / 6);
    assert.ok(liftedThigh.sub(thigh).dot(toeDirection) > 0,
      `${side} forward hip lift must move the knee toward the toes`);
    assert.ok(forwardHipDegrees(-Math.PI / 6) > 0);
  }
});
