"""3D model export for any engine. Usage: blender -b --python export_models.py -- payload.json
job: {name, kind, params, export:{formats, up, forward, meters_per_tile, bake, texture_size, lods:[tris|null,...]}}
Every piece is built in tile units; scaled to metres on export. Canonical model front = Blender -Y."""
import json
import math
import os
import sys

pj = sys.argv[sys.argv.index("--") + 1]
payload = json.load(open(pj))
sys.path.insert(0, payload["blender_dir"])
import bpy  # noqa: E402
import kitbash  # noqa: E402
import scene_rig as rig  # noqa: E402
from mathutils import Vector  # noqa: E402

out_dir = payload["out_dir"]
os.makedirs(out_dir, exist_ok=True)


def sel(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o


def to_blender_dir(forward, up):
    f = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}[forward]
    # file space -> Blender: y-up files have (fx,fy,fz) = (bx, bz, -by)
    b = (f[0], -f[2], f[1]) if up == "y" else f
    if abs(b[2]) > 0:
        raise ValueError(f"forward '{forward}' is the up axis for up='{up}'; pick a horizontal axis")
    return Vector(b)


def reduce_tris(o, budget):
    sel(o)
    tri = o.modifiers.new("tri", "TRIANGULATE")
    bpy.ops.object.modifier_apply(modifier=tri.name)
    n = len(o.data.polygons)
    if budget and n > budget:
        dm = o.modifiers.new("dec", "DECIMATE")
        dm.ratio = budget / n
        bpy.ops.object.modifier_apply(modifier=dm.name)


def bake_albedo(o, size, path):
    """Bake whatever the (procedural/AI-textured) materials look like into one image + one simple material."""
    sc = bpy.context.scene
    sel(o)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.012)
    bpy.ops.object.mode_set(mode="OBJECT")
    img = bpy.data.images.new(o.name + "_albedo", size, size)
    for m in o.data.materials:
        n = m.node_tree.nodes.new("ShaderNodeTexImage")
        n.image = img
        m.node_tree.nodes.active = n
    sc.render.engine = "CYCLES"
    sc.cycles.samples, sc.cycles.device = 1, "CPU"
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=6)
    img.filepath_raw, img.file_format = path, "PNG"
    img.save()
    nm = bpy.data.materials.new(o.name + "_baked")
    nm.use_nodes = True
    b = nm.node_tree.nodes["Principled BSDF"]
    t = nm.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(path)
    nm.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.85
    o.data.materials.clear()
    o.data.materials.append(nm)
    sc.render.engine = "BLENDER_EEVEE"


def orient_scale(o, forward, up, mpt):
    t = to_blender_dir(forward, up)
    ang = math.atan2(t.y, t.x) - math.atan2(-1, 0)  # canonical front is -Y
    o.rotation_euler.z = ang
    o.scale = (o.scale.x * mpt,) * 3
    sel(o)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def export(o, base, fmt, up):
    sel(o)
    path = f"{base}.{fmt}"
    y = up == "y"
    if fmt == "glb":
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=True, export_yup=y)
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=path, use_selection=True, axis_forward="-Z" if y else "Y", axis_up="Y" if y else "Z",
                                 path_mode="COPY", embed_textures=True)
    elif fmt == "obj":
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True,
                              forward_axis="NEGATIVE_Z" if y else "Y", up_axis="Y" if y else "Z")
    elif fmt == "usdz":
        bpy.ops.wm.usd_export(filepath=path, selected_objects_only=True)
    else:
        raise ValueError(f"unknown format {fmt}")
    return path


def export_character(job, ex):
    """Skinned humanoid + all animations. Built in metres; no LODs (decimation would break skin weights)."""
    import character as C
    p = job.get("params", {})
    b = dict(p.get("build", {}))
    if ex.get("height_m"):
        b["scale"] = ex["height_m"] / 1.72 * ex.get("scale", 1.0)   # the humanoid is 1.72 m at scale 1
    elif ex.get("scale"):
        b["scale"] = b.get("scale", 1.0) * ex["scale"]
    arm, mesh = C.build(cfg, p.get("preset", "survivor"), **b)
    C.make_actions(arm, arm["hunch"], p.get("anims") or list(C.ANIMS))
    base = os.path.join(out_dir, job["name"])
    files = []
    if ex.get("bake", True):
        bake_albedo(mesh, int(ex.get("texture_size", 512)), base + "_albedo.png")
        files.append(base + "_albedo.png")
    arm.rotation_euler.z = math.atan2(*reversed(tuple(to_blender_dir(ex.get("forward", "+z"), ex.get("up", "y")).xy))) - math.atan2(-1, 0)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    up, formats = ex.get("up", "y"), {}
    for fmt in ex.get("formats", ["glb"]):
        path = f"{base}.{fmt}"
        if fmt == "glb":
            bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=True, export_apply=False,
                                      export_yup=up == "y", export_animation_mode="ACTIONS")
        elif fmt == "fbx":
            bpy.ops.export_scene.fbx(filepath=path, use_selection=True, axis_forward="-Z" if up == "y" else "Y",
                                     axis_up="Y" if up == "y" else "Z", path_mode="COPY", embed_textures=True,
                                     bake_anim=True, bake_anim_use_all_actions=True, add_leaf_bones=False)
        else:
            continue  # obj/usdz carry no skeleton animation here
        formats[fmt] = path
    files += list(formats.values())
    return [{"name": job["name"], "lod": 0, "tris": len(mesh.data.polygons), "files": formats, "all_files": files,
             "animations": [a.name for a in bpy.data.actions]}]


results = []
for job in payload["jobs"]:
    ex = job.get("export", {})
    rig.reset()
    cfg = payload["cfg"]
    if job["kind"] == "character":
        results += export_character(job, ex)
        continue
    src = kitbash.build(cfg, job["kind"], **job.get("params", {}))
    mpt = ex.get("meters_per_tile", 2.0) * ex.get("scale", 1.0)
    if ex.get("height_m"):   # fit the model to an exact real-world height
        mpt = ex["height_m"] / max(src.dimensions.z, 1e-6)
    for li, budget in enumerate(ex.get("lods") or [None]):
        o = src.copy()
        o.data = src.data.copy()
        bpy.context.scene.collection.objects.link(o)
        suffix = f"_lod{li}" if len(ex.get("lods") or [None]) > 1 else ""
        base = os.path.join(out_dir, job["name"] + suffix)
        reduce_tris(o, budget)
        files = []
        if ex.get("bake", True):
            size = max(128, int(ex.get("texture_size", 512)) >> li)
            bake_albedo(o, size, base + "_albedo.png")
            files.append(base + "_albedo.png")
        orient_scale(o, ex.get("forward", "+z"), ex.get("up", "y"), mpt)
        formats = {f: export(o, base, f, ex.get("up", "y")) for f in ex.get("formats", ["glb"])}
        for f, p in formats.items():
            files.append(p)
            if f == "obj":
                files.append(base + ".mtl")
        results.append({"name": job["name"], "lod": li, "tris": len(o.data.polygons), "files": formats,
                        "all_files": [f for f in files if os.path.exists(f)]})
json.dump(results, open(pj.replace(".json", ".result.json"), "w"))
