import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { PropertyBinding } from "../site/vendor/three.module.js";

test("the shipped Tripo human is skinned and exposes the hip and knee bones used by the viewer", () => {
  const bytes = readFileSync(new URL("../site/assets/human-tripo-rigged.glb", import.meta.url));
  assert.equal(bytes.toString("utf8", 0, 4), "glTF");
  const jsonLength = bytes.readUInt32LE(12);
  assert.equal(bytes.toString("utf8", 16, 20), "JSON");
  const model = JSON.parse(bytes.subarray(20, 20 + jsonLength).toString("utf8"));
  assert.ok(model.skins?.length > 0);
  const names = new Set(model.nodes.map((node) => PropertyBinding.sanitizeNodeName(node.name || "")));
  for (const name of ["mixamorigHips", "mixamorigLeftUpLeg", "mixamorigRightUpLeg", "mixamorigLeftLeg", "mixamorigRightLeg"])
    assert.ok(names.has(name), `missing ${name}`);
});
