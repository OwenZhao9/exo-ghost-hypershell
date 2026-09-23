# Human visual model source

The local `site/` viewer uses `site/assets/human-tripo-rigged.glb`. This asset is a visual approximation, not an official Hypershell model or a scan of a real wearer.

## Source and generation

- Official reference: [Hypershell studio wearer photograph](https://hypershell.tech/en-us/products/hypershell-x), image `HypershellGOX-9_1880x.jpg`; the owner confirmed official material permission for the competition. It guided the character's natural proportions and clean presentation, not its face or identity.
- Reference input: `human-membrane-reference.png`, generated with the built-in image generation tool from the official photograph's body proportions. The initial draft had a realistic face; after the owner's correction it was edited into a smooth, seamless, white membrane mannequin in a front A-pose, with no facial features, hair, garments or shoes. The earlier face draft is not used by the viewer.
- Tripo image-to-model task: `47320e97-7fee-44db-a153-5b69afcbb068`, `v3.1-20260211`, PBR and detailed texture, 50,000 face limit; 40 credits.
- Tripo rig-check task: `999373ef-7c2a-48b2-a777-af2879501cda`; result: biped riggable; 0 credits.
- Tripo auto-rig task: `b3de044f-c304-48ec-b633-3b84b779b2b8`, biped, `v1.0-20240301`, Mixamo bone names, GLB output; 25 credits.

The Tripo API credential stays in macOS Keychain and is not in this repository. For regeneration, consult `/Users/owenzhao/tripo3D 比赛/TRIPO_API_AGENT_GUIDE.md` and query the existing task IDs before creating new tasks. The source PNG and rigged GLB have been retained here to make the visual asset reproducible without exposing signed download URLs. The local viewer hides the generated color texture and renders the rigged mesh in translucent white.
