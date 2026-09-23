"""Render local Ghost GLB assets as transparent website product images.

Run with Blender: blender -b --factory-startup --python tools/render_site_models.py
"""

from pathlib import Path
import subprocess

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "site" / "assets"
OUTPUT = ASSETS / "renders"
OUTPUT.mkdir(exist_ok=True)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def add_area(name, location, power, color, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power
    data.color = color
    data.shape = "DISK"
    data.size = size
    light = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(light)
    light.location = location
    light.rotation_euler = (Vector((0, 0, 0)) - light.location).to_track_quat("-Z", "Y").to_euler()


def render_model(source, name, views, *, white=False):
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(ASSETS / source))
    meshes = [
        obj for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.name.startswith("tripo_")
    ]
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and obj not in meshes:
            obj.hide_render = True
    if white:
        material = bpy.data.materials.new("Ghost white membrane")
        material.diffuse_color = (0.91, 0.94, 0.95, 1)
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (0.91, 0.94, 0.95, 1)
        bsdf.inputs["Roughness"].default_value = 0.72
        for mesh in meshes:
            mesh.data.materials.clear()
            mesh.data.materials.append(material)

    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    center = Vector(tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in range(3)))
    extent = max(max(p[i] for p in points) - min(p[i] for p in points) for i in range(3))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.resolution_x = 1200
    scene.render.resolution_y = 1200
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.view_settings.view_transform = "AgX"
    scene.world.color = (0.27, 0.31, 0.38)

    add_area("Softbox", (3.5, -4.5, 5), 850, (0.89, 0.96, 1), 5)
    add_area("Fill", (-4, -2, 2), 550, (0.68, 0.82, 1), 4)
    add_area("Rim", (1, 4, 3), 1100, (1, 0.71, 0.37), 3)

    camera_data = bpy.data.cameras.new("Product camera")
    camera = bpy.data.objects.new("Product camera", camera_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = extent * 1.43

    for label, direction in views.items():
        camera.location = center + Vector(direction).normalized() * extent * 3.2
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        png = OUTPUT / f"{name}-{label}.png"
        scene.render.filepath = str(png)
        bpy.ops.render.render(write_still=True)
        subprocess.run(
            ["cwebp", "-quiet", "-q", "86", "-alpha_q", "100", str(png),
             "-o", str(png.with_suffix(".webp"))],
            check=True,
        )
        png.unlink()


render_model(
    "exoskeleton.glb",
    "exoskeleton",
    {"front": (0, -5, 1.7), "angle": (4, -4, 2.0), "rear": (0, 5, 1.7)},
)
render_model("human-tripo-rigged.glb", "human", {"angle": (4, -4, 2.0)}, white=True)
