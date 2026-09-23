# Human model provenance

`human-tripo-rigged.glb` is a generated visual character for the local Ghost 3D view. It is not an official Hypershell 3D model, a scan of a real person, or an anatomical measurement tool.

- Reference styling and proportions: [Hypershell official studio wearer photograph](https://hypershell.tech/en-us/products/hypershell-x) (`HypershellGOX-9_1880x.jpg`). The device owner confirmed permission to use official Hypershell material for this competition. The reference is used for overall presentation only; the character does not copy the photographed person's identity or equipment.
- A neutral, featureless white membrane front view was prepared from that reference and is stored at `../../model-sources/human-membrane-reference.png`.
- The 3D mesh was generated with Tripo image-to-model v3.1 from that front view, then rigged with Tripo's humanoid auto-rig in Mixamo bone format. Task IDs and cost are in `../../model-sources/README.md`.
- In `site/app.js`, the source texture is hidden, the surface is rendered as translucent white, and the character is turned to face the exoskeleton's wearing direction. Its rigged hips follow the same measured left/right angles as the exoskeleton.

The legacy Cesium Rigged Figure sample was removed from the site assets.
