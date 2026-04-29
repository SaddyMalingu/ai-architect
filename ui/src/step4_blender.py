# src/step4_blender.py
import os
import shutil
import subprocess
import textwrap

BLENDER_EXEC = "blender"  # can be overridden by env var BLENDER_EXEC



BLENDER_SCRIPT = """\
import bpy
import addon_utils
import json
import math
import sys
import os
from mathutils import Vector
import bmesh

# Add custom add-on paths so Blender can find them
sys.path.append(r'C:/Users/I.A Journal hub/ai_architect/addons/archipack')
sys.path.append(r'C:/Users/I.A Journal hub/ai_architect/addons/sverchok')
sys.path.append(r'C:/Users/I.A Journal hub/ai_architect/addons/modulartree')

# Enable add-ons if present
for addon in ['archipack', 'sverchok', 'modulartree', 'archimesh', 'add_mesh_extra_objects']:
    try:
        addon_utils.enable(addon)
    except Exception as e:
        print(f"Add-on not enabled: {addon}, reason: {e}")

# remove default
bpy.ops.wm.read_factory_settings(use_empty=True)

# import glb
infile = __INFILE__
specs_path = __SPECS__
identity_path = __IDENTITY__
specs = {}
house_identity = {}
try:
    if specs_path and os.path.exists(specs_path):
        with open(specs_path, "r", encoding="utf-8") as f:
            specs = json.load(f)
except Exception:
    specs = {}
try:
    if identity_path and os.path.exists(identity_path):
        with open(identity_path, "r", encoding="utf-8") as f:
            house_identity = json.load(f)
except Exception:
    house_identity = {}
bpy.ops.import_scene.gltf(filepath=infile)

def get_mesh_objects():
    return [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']

# collect mesh objects
mesh_objects = get_mesh_objects()

def get_scene_bounds(objects):
    if not objects:
        return None, None
    min_v = [float('inf')] * 3
    max_v = [float('-inf')] * 3
    for obj in objects:
        for v in obj.bound_box:
            wv = obj.matrix_world @ Vector(v)
            for i in range(3):
                min_v[i] = min(min_v[i], wv[i])
                max_v[i] = max(max_v[i], wv[i])
    return min_v, max_v

min_v, max_v = get_scene_bounds(mesh_objects)

def delete_objects(objs):
    if not objs:
        return
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objs:
        obj.select_set(True)
    bpy.ops.object.delete()

def make_boolean_cut(target, cutter):
    mod = target.modifiers.new(name="Boolean", type='BOOLEAN')
    mod.operation = 'DIFFERENCE'
    mod.object = cutter
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)

def build_house_shell(min_v, max_v):
    if not min_v or not max_v:
        return

    house_w = (max_v[0] - min_v[0]) + 0.8
    house_d = (max_v[1] - min_v[1]) + 0.8
    wall_h = 3.0
    wall_t = 0.2
    center = ((min_v[0] + max_v[0]) / 2, (min_v[1] + max_v[1]) / 2, wall_h / 2)

    porch_enabled = bool(specs.get("porch", True))
    garage_enabled = bool(specs.get("garage", True))
    dormer_enabled = bool(specs.get("dormer", False))
    roof_type = (specs.get("roof_type") or "gable").lower()
    window_pattern = (specs.get("window_pattern") or "symmetrical").lower()
    site = specs.get("site", {}) or {}
    driveway_enabled = bool(site.get("driveway", True))
    try:
        trees_count = int(site.get("trees", 2) or 0)
    except Exception:
        trees_count = 2

    identity = house_identity if isinstance(house_identity, dict) else {}
    entry_cfg = identity.get("entry", {}) or {}
    massing_cfg = identity.get("massing", {}) or {}
    garage_cfg = identity.get("garage", {}) or {}
    roof_cfg = identity.get("roof", {}) or {}
    facade_cfg = identity.get("facades", {}) or {}
    site_identity = identity.get("site", {}) or {}

    secondary_side = massing_cfg.get("secondary_volume_side") or "left"
    secondary_sign = -1 if secondary_side == "left" else 1
    secondary_offset_ratio = float(massing_cfg.get("secondary_volume_offset_ratio", 0.35) or 0.35)
    secondary_width_ratio = float(massing_cfg.get("secondary_volume_width_ratio", 0.45) or 0.45)
    secondary_depth_ratio = float(massing_cfg.get("secondary_volume_depth_ratio", 0.45) or 0.45)
    door_offset_ratio = float(entry_cfg.get("door_offset_ratio", 0.0) or 0.0)
    garage_side = garage_cfg.get("side") or ("right" if garage_enabled else "none")
    garage_sign = -1 if garage_side == "left" else 1
    garage_width_ratio = float(garage_cfg.get("width_ratio", 0.5) or 0.5)
    garage_depth_ratio = float(garage_cfg.get("depth_ratio", 0.5) or 0.5)
    garage_front_offset_ratio = float(garage_cfg.get("front_offset_ratio", 0.1) or 0.1)
    gable_facade = roof_cfg.get("gable_facade") or "front"
    dormer_offset_ratio = float(roof_cfg.get("dormer_offset_ratio", 0.0) or 0.0)
    driveway_offset_ratio = float(site_identity.get("driveway_offset_ratio", door_offset_ratio) or 0.0)
    tree_arc_ratio = float(site_identity.get("tree_arc_ratio", 0.9) or 0.9)

    def add_gable(width, depth, height, center_pos, name):
        mesh = bpy.data.meshes.new("Gable")
        obj = bpy.data.objects.new("Gable", mesh)
        bpy.context.scene.collection.objects.link(obj)

        bm = bmesh.new()
        w = width / 2
        d = depth / 2

        v1 = bm.verts.new((-w, -d, 0))
        v2 = bm.verts.new((w, -d, 0))
        v3 = bm.verts.new((0, -d, height))
        v4 = bm.verts.new((-w, d, 0))
        v5 = bm.verts.new((w, d, 0))
        v6 = bm.verts.new((0, d, height))

        bm.faces.new([v1, v2, v3])
        bm.faces.new([v4, v6, v5])
        bm.faces.new([v1, v4, v5, v2])
        bm.faces.new([v2, v5, v6, v3])
        bm.faces.new([v3, v6, v4, v1])

        bm.to_mesh(mesh)
        bm.free()

        obj.location = center_pos
    obj.name = name
        return obj

    # porch
    porch_w = min(house_w * 0.55, 4.6)
    porch_d = 1.8
    if porch_enabled:
        porch_center = (center[0], center[1] - house_d / 2 - porch_d / 2 + 0.05, 0.08)
        bpy.ops.mesh.primitive_cube_add(size=1, location=porch_center)
        porch = bpy.context.object
        porch.name = "Porch"
        porch.scale = (porch_w / 2, porch_d / 2, 0.08)

        # porch railing
        rail_h = 0.9
        rail_t = 0.05
        # front rail
        rail_center = (center[0], porch_center[1] - porch_d / 2 + rail_t, rail_h / 2)
        bpy.ops.mesh.primitive_cube_add(size=1, location=rail_center)
        rail = bpy.context.object
        rail.name = "Trim_Porch_Rail_Front"
        rail.scale = (porch_w / 2, rail_t / 2, rail_h / 2)
        # side rails
        for sign in (-1, 1):
            side_center = (center[0] + sign * (porch_w / 2 - rail_t), porch_center[1], rail_h / 2)
            bpy.ops.mesh.primitive_cube_add(size=1, location=side_center)
            side_rail = bpy.context.object
            side_rail.name = f"Trim_Porch_Rail_Side_{'L' if sign < 0 else 'R'}"
            side_rail.scale = (rail_t / 2, porch_d / 2, rail_h / 2)

        # porch steps
        step_h = 0.12
        step_d = 0.35
        for i in range(3):
            step_center = (center[0], porch_center[1] - porch_d / 2 - step_d * (i + 0.5), step_h * (i + 0.5))
            bpy.ops.mesh.primitive_cube_add(size=1, location=step_center)
            step = bpy.context.object
            step.name = f"Porch_Step_{i}"
            step.scale = (porch_w / 2, step_d / 2, step_h / 2)

        # porch columns
        col_radius = 0.08
        col_height = 2.4
        col_offsets = [(-porch_w * 0.4, 0), (porch_w * 0.4, 0)]
        for i, (ox, oy) in enumerate(col_offsets):
            bpy.ops.mesh.primitive_cylinder_add(radius=col_radius, depth=col_height,
                                                location=(center[0] + ox, porch_center[1] + porch_d * 0.2 + oy, col_height / 2))
            col = bpy.context.object
            col.name = f"Porch_Column_{i}"

        # porch roof overhang
        bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1] - house_d / 2 - porch_d / 2 + 0.05, wall_h + 0.4))
        porch_roof = bpy.context.object
        porch_roof.name = "Roof_Porch"
        porch_roof.scale = (porch_w / 2 + 0.3, porch_d / 2 + 0.3, 0.08)

    # outer block
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    outer = bpy.context.object
    outer.name = "Wall_Shell"
    outer.scale = (house_w / 2, house_d / 2, wall_h / 2)

    # secondary volume (massing)
    sec_w = house_w * secondary_width_ratio
    sec_d = house_d * secondary_depth_ratio
    sec_center = (center[0] + secondary_sign * house_w * secondary_offset_ratio, center[1] + house_d * 0.15, wall_h / 2)
    bpy.ops.mesh.primitive_cube_add(size=1, location=sec_center)
    secondary = bpy.context.object
    secondary.name = "Volume_Secondary"
    secondary.scale = (sec_w / 2, sec_d / 2, wall_h / 2)

    # inner block for hollowing
    inner_w = max(house_w - wall_t * 2, 1.0)
    inner_d = max(house_d - wall_t * 2, 1.0)
    bpy.ops.mesh.primitive_cube_add(size=1, location=center)
    inner = bpy.context.object
    inner.scale = (inner_w / 2, inner_d / 2, wall_h / 2)

    make_boolean_cut(outer, inner)
    delete_objects([inner])

    # base plinth
    bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1], 0.08))
    plinth = bpy.context.object
    plinth.name = "Plinth"
    plinth.scale = (house_w / 2 + 0.15, house_d / 2 + 0.15, 0.08)

    # door opening
    door_w = 1.2
    door_h = 2.2
    door_center = (center[0] + house_w * door_offset_ratio, center[1] - house_d / 2 - 0.001, door_h / 2)
    bpy.ops.mesh.primitive_cube_add(size=1, location=door_center)
    door_cut = bpy.context.object
    door_cut.scale = (door_w / 2, 0.3, door_h / 2)
    make_boolean_cut(outer, door_cut)
    delete_objects([door_cut])

    # windows
    window_w = 1.4
    window_h = 1.0
    window_z = 1.5

    def add_window_feature(facade_name, bay, index):
        bay_offset_ratio = float(bay.get("offset_ratio", 0.0) or 0.0)
        local_width_ratio = float(bay.get("width_ratio", 0.16) or 0.16)
        local_height_ratio = float(bay.get("height_ratio", 0.32) or 0.32)
        shutters_enabled = bool(bay.get("shutters", False))

        if facade_name in {"front", "rear"}:
            local_window_w = max(1.0, house_w * local_width_ratio)
            local_window_h = max(0.9, wall_h * local_height_ratio)
            wall_y = center[1] - house_d / 2 - 0.001 if facade_name == "front" else center[1] + house_d / 2 + 0.001
            trim_y = wall_y - 0.02 if facade_name == "front" else wall_y + 0.02
            win_center = (center[0] + house_w * bay_offset_ratio, wall_y, window_z)
            is_front_back = True
        else:
            local_window_w = max(1.0, house_d * local_width_ratio)
            local_window_h = max(0.9, wall_h * local_height_ratio)
            wall_x = center[0] - house_w / 2 - 0.001 if facade_name == "left" else center[0] + house_w / 2 + 0.001
            trim_x = wall_x - 0.02 if facade_name == "left" else wall_x + 0.02
            win_center = (wall_x, center[1] + house_d * bay_offset_ratio, window_z)
            is_front_back = False

        bpy.ops.mesh.primitive_cube_add(size=1, location=win_center)
        win_cut = bpy.context.object
        if is_front_back:
            win_cut.scale = (local_window_w / 2, 0.3, local_window_h / 2)
        else:
            win_cut.scale = (0.3, local_window_w / 2, local_window_h / 2)
        make_boolean_cut(outer, win_cut)
        delete_objects([win_cut])

        # glass pane
        bpy.ops.mesh.primitive_cube_add(size=1, location=win_center)
        glass = bpy.context.object
        if is_front_back:
            glass.scale = (local_window_w / 2, 0.02, local_window_h / 2)
        else:
            glass.scale = (0.02, local_window_w / 2, local_window_h / 2)
        glass.name = f"Window_{facade_name.title()}_{index}"

        # window frame
        bpy.ops.mesh.primitive_cube_add(size=1, location=win_center)
        frame = bpy.context.object
        if is_front_back:
            frame.scale = (local_window_w / 2 + 0.06, 0.03, local_window_h / 2 + 0.06)
        else:
            frame.scale = (0.03, local_window_w / 2 + 0.06, local_window_h / 2 + 0.06)
        frame.name = f"Trim_Window_{facade_name.title()}_{index}"

        # recessed window (depth) and sill/header
        recess_depth = 0.08
        if is_front_back:
            inset_loc = (win_center[0], trim_y, win_center[2])
            inset_scale = (local_window_w / 2 - 0.1, recess_depth / 2, local_window_h / 2 - 0.1)
            sill_scale = (local_window_w / 2 + 0.05, 0.03, 0.04)
        else:
            inset_loc = (trim_x, win_center[1], win_center[2])
            inset_scale = (recess_depth / 2, local_window_w / 2 - 0.1, local_window_h / 2 - 0.1)
            sill_scale = (0.03, local_window_w / 2 + 0.05, 0.04)

        bpy.ops.mesh.primitive_cube_add(size=1, location=inset_loc)
        recess = bpy.context.object
        recess.name = f"Trim_Recess_{facade_name.title()}_{index}"
        recess.scale = inset_scale

        bpy.ops.mesh.primitive_cube_add(size=1, location=(win_center[0], win_center[1], win_center[2] - local_window_h / 2 - 0.03))
        sill = bpy.context.object
        sill.name = f"Trim_Sill_{facade_name.title()}_{index}"
        sill.scale = sill_scale

        bpy.ops.mesh.primitive_cube_add(size=1, location=(win_center[0], win_center[1], win_center[2] + local_window_h / 2 + 0.03))
        header = bpy.context.object
        header.name = f"Trim_Header_{facade_name.title()}_{index}"
        header.scale = sill_scale

        # mullions
        bpy.ops.mesh.primitive_cube_add(size=1, location=win_center)
        mull_v = bpy.context.object
        if is_front_back:
            mull_v.scale = (0.03, 0.02, local_window_h / 2)
        else:
            mull_v.scale = (0.02, 0.03, local_window_h / 2)
        mull_v.name = f"Trim_Mullion_V_{facade_name.title()}_{index}"

        bpy.ops.mesh.primitive_cube_add(size=1, location=win_center)
        mull_h = bpy.context.object
        if is_front_back:
            mull_h.scale = (local_window_w / 2, 0.02, 0.03)
        else:
            mull_h.scale = (0.02, local_window_w / 2, 0.03)
        mull_h.name = f"Trim_Mullion_H_{facade_name.title()}_{index}"

        if shutters_enabled and facade_name == "front":
            shutter_w = 0.35
            shutter_h = local_window_h + 0.1
            shutter_offset = local_window_w / 2 + shutter_w / 2 + 0.05
            for side in (-1, 1):
                bpy.ops.mesh.primitive_cube_add(size=1, location=(win_center[0] + side * shutter_offset, win_center[1] - 0.02, window_z))
                shutter = bpy.context.object
                shutter.name = f"Trim_Shutter_{facade_name.title()}_{index}_{'L' if side < 0 else 'R'}"
                shutter.scale = (shutter_w / 2, 0.02, shutter_h / 2)

    default_facades = {
        "front": {"window_bays": [{"offset_ratio": -0.25, "width_ratio": 0.17, "height_ratio": 0.32, "shutters": True}, {"offset_ratio": 0.25, "width_ratio": 0.17, "height_ratio": 0.32, "shutters": True}]},
        "rear": {"window_bays": [{"offset_ratio": -0.22, "width_ratio": 0.16, "height_ratio": 0.32}, {"offset_ratio": 0.22, "width_ratio": 0.16, "height_ratio": 0.32}]},
        "left": {"window_bays": [{"offset_ratio": 0.0, "width_ratio": 0.16, "height_ratio": 0.32}]},
        "right": {"window_bays": [{"offset_ratio": 0.0, "width_ratio": 0.16, "height_ratio": 0.32}]},
    }
    for facade_name in ("front", "rear", "left", "right"):
        facade = facade_cfg.get(facade_name) or default_facades[facade_name]
        for index, bay in enumerate(facade.get("window_bays") or []):
            add_window_feature(facade_name, bay, index)

    # floor slab
    bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1], 0.1))
    floor = bpy.context.object
    floor.name = "Floor"
    floor.scale = (house_w / 2, house_d / 2, 0.1)

    # ceiling slab
    bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1], wall_h + 0.06))
    ceiling = bpy.context.object
    ceiling.name = "Ceiling"
    ceiling.scale = (house_w / 2, house_d / 2, 0.06)

    # garage volume + door opening
    if garage_enabled:
        garage_w = min(house_w * garage_width_ratio, 4.8)
        garage_d = min(house_d * garage_depth_ratio, 4.2)
        garage_center = (center[0] + garage_sign * house_w * 0.35, center[1] - house_d * garage_front_offset_ratio, wall_h / 2)
        bpy.ops.mesh.primitive_cube_add(size=1, location=garage_center)
        garage = bpy.context.object
        garage.name = "Garage"
        garage.scale = (garage_w / 2, garage_d / 2, wall_h / 2)

        # garage door cut
        garage_door_w = 2.4
        garage_door_h = 2.2
        garage_front = (garage_center[0], garage_center[1] - garage_d / 2 - 0.001, garage_door_h / 2)
        bpy.ops.mesh.primitive_cube_add(size=1, location=garage_front)
        garage_cut = bpy.context.object
        garage_cut.scale = (garage_door_w / 2, 0.3, garage_door_h / 2)
        make_boolean_cut(garage, garage_cut)
        delete_objects([garage_cut])

        # garage door panel
        bpy.ops.mesh.primitive_cube_add(size=1, location=(garage_front[0], garage_front[1] - 0.05, garage_front[2]))
        garage_door = bpy.context.object
        garage_door.name = "Garage_Door"
        garage_door.scale = (garage_door_w / 2, 0.03, garage_door_h / 2)

        # garage roof tie-in
        bpy.ops.mesh.primitive_cube_add(size=1, location=(garage_center[0], garage_center[1], wall_h + 0.5))
        garage_roof = bpy.context.object
        garage_roof.name = "Roof_Garage"
        garage_roof.scale = (garage_w / 2 + 0.2, garage_d / 2 + 0.2, 0.12)
        garage_roof.rotation_euler[0] = math.radians(15)

        # ridge/valley connection piece
        bpy.ops.mesh.primitive_cube_add(size=1, location=(garage_center[0] - garage_sign * garage_w / 2, garage_center[1] + garage_d / 2, wall_h + 0.55))
        connection = bpy.context.object
        connection.name = "Roof_Connection"
        connection.scale = (0.3, 0.6, 0.08)

    # gable accent
    gable_height = 1.2
    gable_depth = 0.2
    gable_center = (center[0], center[1] - house_d / 2 + 0.02, wall_h) if gable_facade == "front" else (center[0], center[1] + house_d / 2 - 0.02, wall_h)
    gable_width = (porch_w + 0.8) if porch_enabled else (house_w * 0.7)
    add_gable(gable_width, gable_depth, gable_height, gable_center, f"Gable_{gable_facade.title()}")

    # dormer
    if dormer_enabled:
        dormer_w = 1.6
        dormer_d = 1.2
        dormer_h = 1.2
        dormer_center = (center[0] + house_w * dormer_offset_ratio, center[1], wall_h + 0.6)
        bpy.ops.mesh.primitive_cube_add(size=1, location=dormer_center)
        dormer = bpy.context.object
        dormer.name = "Dormer"
        dormer.scale = (dormer_w / 2, dormer_d / 2, dormer_h / 2)

        bpy.ops.mesh.primitive_cube_add(size=1, location=(dormer_center[0], dormer_center[1] - dormer_d / 2 - 0.001, dormer_center[2]))
        dormer_win = bpy.context.object
        dormer_win.name = "Window_Dormer"
        dormer_win.scale = (0.5, 0.02, 0.5)

    # roof slabs
    roof_h = 1.1
    roof_overhang = 0.3
    if roof_type == "flat":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1], wall_h + 0.2))
        roof = bpy.context.object
        roof.name = "Roof_Flat"
        roof.scale = ((house_w + roof_overhang * 2) / 2, (house_d + roof_overhang * 2) / 2, 0.12)

        # parapet
        parapet_h = 0.25
        parapet_t = 0.08
        for sign in (-1, 1):
            bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1] + sign * (house_d / 2 + roof_overhang), wall_h + 0.35))
            parapet = bpy.context.object
            parapet.name = f"Parapet_{'F' if sign < 0 else 'B'}"
            parapet.scale = ((house_w + roof_overhang * 2) / 2, parapet_t / 2, parapet_h / 2)
        for sign in (-1, 1):
            bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0] + sign * (house_w / 2 + roof_overhang), center[1], wall_h + 0.35))
            parapet = bpy.context.object
            parapet.name = f"Parapet_{'L' if sign < 0 else 'R'}"
            parapet.scale = (parapet_t / 2, (house_d + roof_overhang * 2) / 2, parapet_h / 2)
    elif roof_type == "hip":
        bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1], wall_h + 0.4))
        roof = bpy.context.object
        roof.name = "Roof_Hip"
        roof.scale = ((house_w + roof_overhang * 2) / 2, (house_d + roof_overhang * 2) / 2, 0.2)
    else:
        for sign in (-1, 1):
            bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1] + sign * house_d * 0.25, wall_h + roof_h / 2))
            roof = bpy.context.object
            roof.name = f"Roof_{'Left' if sign < 0 else 'Right'}"
            roof.scale = ((house_w + roof_overhang * 2) / 2, (house_d / 2 + roof_overhang) / 2, 0.15)
            roof.rotation_euler[0] = math.radians(30 * sign)

        # gutters + downspouts
        gutter_t = 0.05
        gutter_h = 0.05
        bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1] - house_d / 2 - roof_overhang + 0.02, wall_h + 0.05))
        gutter = bpy.context.object
        gutter.name = "Gutter_Front"
        gutter.scale = ((house_w + roof_overhang * 2) / 2, gutter_t / 2, gutter_h / 2)
        downspout_x = center[0] + house_w / 2 + roof_overhang - 0.05
        if garage_enabled:
            downspout_x = garage_center[0] + garage_w / 2 - 0.05
        bpy.ops.mesh.primitive_cube_add(size=1, location=(downspout_x, center[1] - house_d / 2 - roof_overhang + 0.02, 1.2))
        downspout = bpy.context.object
        downspout.name = "Downspout"
        downspout.scale = (0.05, 0.05, 1.2)

    # facade trim line + cornice band
    bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1] - house_d / 2 - 0.001, wall_h * 0.75))
    trim = bpy.context.object
    trim.name = "Trim_Facade"
    trim.scale = (house_w / 2, 0.03, 0.05)

    bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1], wall_h * 0.75))
    band = bpy.context.object
    band.name = "Trim_Band"
    band.scale = (house_w / 2 + 0.02, house_d / 2 + 0.02, 0.04)

    # driveway
    if driveway_enabled:
        driveway_x = center[0] + house_w * driveway_offset_ratio
        bpy.ops.mesh.primitive_cube_add(size=1, location=(driveway_x, center[1] - house_d / 2 - 3.0, 0.02))
        driveway = bpy.context.object
        driveway.name = "Driveway"
        driveway.scale = (1.25, 3.0, 0.02)

        # driveway curb
        curb_t = 0.06
        curb_h = 0.08
        for sign in (-1, 1):
            curb_center = (driveway_x + sign * (1.25 + curb_t), center[1] - house_d / 2 - 3.0, curb_h / 2)
            bpy.ops.mesh.primitive_cube_add(size=1, location=curb_center)
            curb = bpy.context.object
            curb.name = f"Trim_Driveway_Curb_{'L' if sign < 0 else 'R'}"
            curb.scale = (curb_t / 2, 3.0, curb_h / 2)

    # walkway
    if driveway_enabled:
        bpy.ops.mesh.primitive_cube_add(size=1, location=(door_center[0], center[1] - house_d / 2 - 1.2, 0.02))
        walk = bpy.context.object
        walk.name = "Walkway"
        walk.scale = (0.4, 1.6, 0.02)

    # landscape bed
    bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1] - house_d / 2 - 0.4, 0.04))
    bed = bpy.context.object
    bed.name = "Landscape_Bed"
    bed.scale = (house_w / 2, 0.35, 0.04)

    # ground
    bpy.ops.mesh.primitive_cube_add(size=1, location=(center[0], center[1], 0.01))
    ground = bpy.context.object
    ground.name = "Ground"
    ground.scale = (house_w, house_d, 0.01)

    # trees
    if trees_count > 0:
        span = house_w * tree_arc_ratio
        denom = max(trees_count - 1, 1)
        for i in range(trees_count):
            x_offset = -span + (2 * span) * (i / denom)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.15, depth=2.0, location=(center[0] + x_offset, center[1] + house_d * 0.9, 1.0))
            trunk = bpy.context.object
            trunk.name = f"Tree_Trunk_{i}"

            bpy.ops.mesh.primitive_ico_sphere_add(radius=0.9, location=(center[0] + x_offset, center[1] + house_d * 0.9, 2.3))
            leaf = bpy.context.object
            leaf.name = f"Tree_Leaf_{i}"

# replace imported meshes with procedural shell
if mesh_objects:
    delete_objects(mesh_objects)
build_house_shell(min_v, max_v)
mesh_objects = get_mesh_objects()

# create camera and frame the scene
cam = bpy.data.cameras.new("Camera")
cam_ob = bpy.data.objects.new("Camera", cam)
bpy.context.scene.collection.objects.link(cam_ob)
bpy.context.scene.camera = cam_ob

if min_v and max_v:
    center = [(min_v[i] + max_v[i]) * 0.5 for i in range(3)]
    size = [max_v[i] - min_v[i] for i in range(3)]
    max_dim = max(size)
    distance = max_dim * 2.5 if max_dim > 0 else 10

    cam_ob.location = (center[0] + distance, center[1] - distance, center[2] + distance * 0.6)

    # look at center
    direction = Vector(center) - cam_ob.location
    cam_ob.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam.clip_start = 0.1
    cam.clip_end = max_dim * 10 if max_dim > 0 else 1000
    cam.lens = 28
    cam.dof.use_dof = True
    cam.dof.focus_distance = distance
    cam.dof.aperture_fstop = 3.2
else:
    cam_ob.location = (10, -10, 8)
    cam_ob.rotation_euler = (1.1, 0, 0.78)

# materials
def get_or_create_material(name, base_color=(0.8, 0.8, 0.8, 1.0), roughness=0.5, metallic=0.0, transmission=0.0):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = base_color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = transmission
        elif "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = transmission
    return mat

def apply_noise_color(mat, color_a, color_b, scale=5.0):
    if not mat or not mat.use_nodes:
        return
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if not bsdf:
        return
    noise = nodes.new(type='ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = scale
    ramp = nodes.new(type='ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = color_a
    ramp.color_ramp.elements[1].color = color_b
    links.new(noise.outputs['Fac'], ramp.inputs['Fac'])
    links.new(ramp.outputs['Color'], bsdf.inputs['Base Color'])

def apply_bump(mat, scale=20.0, strength=0.2):
    if not mat or not mat.use_nodes:
        return
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if not bsdf:
        return
    noise = nodes.new(type='ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = scale
    bump = nodes.new(type='ShaderNodeBump')
    bump.inputs['Strength'].default_value = strength
    links.new(noise.outputs['Fac'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])

def apply_pbr_textures(mat, tex_info):
    if not mat or not mat.use_nodes or not isinstance(tex_info, dict):
        return False
    maps = tex_info.get("maps") or {}
    if not maps:
        return False

    scale = float(tex_info.get("scale") or 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    output = nodes.new(type='ShaderNodeOutputMaterial')
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    links.new(bsdf.outputs['BSDF'], output.inputs['Surface'])

    texcoord = nodes.new(type='ShaderNodeTexCoord')
    mapping = nodes.new(type='ShaderNodeMapping')
    mapping.inputs['Scale'].default_value = (scale, scale, scale)
    links.new(texcoord.outputs['Generated'], mapping.inputs['Vector'])

    def add_image(path, color_space="sRGB"):
        if not path or not os.path.exists(path):
            return None
        img = bpy.data.images.load(path)
        node = nodes.new(type='ShaderNodeTexImage')
        node.image = img
        if color_space != "sRGB":
            node.image.colorspace_settings.name = "Non-Color"
        links.new(mapping.outputs['Vector'], node.inputs['Vector'])
        return node

    def get_map(*keys):
        for k in keys:
            if k in maps and maps[k] and os.path.exists(maps[k]):
                return maps[k]
        return None

    albedo_path = get_map("albedo", "diffuse", "basecolor", "color", "base")
    ao_path = get_map("ao", "ambient_occlusion")
    rough_path = get_map("roughness", "rough", "gloss", "glossiness")
    normal_path = get_map("normal", "nor", "nrm")
    height_path = get_map("height", "displacement", "disp", "bump")

    albedo_node = add_image(albedo_path, "sRGB") if albedo_path else None
    ao_node = add_image(ao_path, "Non-Color") if ao_path else None
    rough_node = add_image(rough_path, "Non-Color") if rough_path else None
    normal_node = add_image(normal_path, "Non-Color") if normal_path else None
    height_node = add_image(height_path, "Non-Color") if height_path else None

    if albedo_node and ao_node:
        mix = nodes.new(type='ShaderNodeMixRGB')
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Fac'].default_value = 1.0
        links.new(albedo_node.outputs['Color'], mix.inputs['Color1'])
        links.new(ao_node.outputs['Color'], mix.inputs['Color2'])
        links.new(mix.outputs['Color'], bsdf.inputs['Base Color'])
    elif albedo_node:
        links.new(albedo_node.outputs['Color'], bsdf.inputs['Base Color'])

    if rough_node:
        links.new(rough_node.outputs['Color'], bsdf.inputs['Roughness'])

    normal_out = None
    if normal_node:
        normal_map = nodes.new(type='ShaderNodeNormalMap')
        links.new(normal_node.outputs['Color'], normal_map.inputs['Color'])
        normal_out = normal_map.outputs['Normal']

    if height_node:
        bump = nodes.new(type='ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.2
        links.new(height_node.outputs['Color'], bump.inputs['Height'])
        if normal_out:
            links.new(normal_out, bump.inputs['Normal'])
        links.new(bump.outputs['Normal'], bsdf.inputs['Normal'])
    elif normal_out:
        links.new(normal_out, bsdf.inputs['Normal'])

    return True

materials = {
    "Wall": get_or_create_material("Mat_Wall", (0.93, 0.93, 0.93, 1.0), roughness=0.7),
    "Roof": get_or_create_material("Mat_Roof", (0.35, 0.2, 0.12, 1.0), roughness=0.6),
    "Floor": get_or_create_material("Mat_Floor", (0.75, 0.75, 0.75, 1.0), roughness=0.8),
    "Ceiling": get_or_create_material("Mat_Ceiling", (0.92, 0.92, 0.92, 1.0), roughness=0.9),
    "Door": get_or_create_material("Mat_Door", (0.35, 0.2, 0.1, 1.0), roughness=0.5),
    "Window": get_or_create_material("Mat_Glass", (0.7, 0.9, 1.0, 1.0), roughness=0.05, transmission=1.0),
    "Ground": get_or_create_material("Mat_Ground", (0.2, 0.35, 0.2, 1.0), roughness=0.9),
    "Room": get_or_create_material("Mat_Room", (0.85, 0.85, 0.88, 1.0), roughness=0.9),
    "Trim": get_or_create_material("Mat_Trim", (0.8, 0.8, 0.82, 1.0), roughness=0.6),
    "Driveway": get_or_create_material("Mat_Driveway", (0.35, 0.35, 0.35, 1.0), roughness=0.95),
    "TreeTrunk": get_or_create_material("Mat_TreeTrunk", (0.25, 0.15, 0.08, 1.0), roughness=0.8),
    "TreeLeaf": get_or_create_material("Mat_TreeLeaf", (0.18, 0.35, 0.18, 1.0), roughness=0.7),
    "Porch": get_or_create_material("Mat_Porch", (0.6, 0.6, 0.62, 1.0), roughness=0.8),
    "Column": get_or_create_material("Mat_Column", (0.85, 0.85, 0.88, 1.0), roughness=0.6),
    "Step": get_or_create_material("Mat_Step", (0.55, 0.55, 0.58, 1.0), roughness=0.8),
    "Gable": get_or_create_material("Mat_Gable", (0.9, 0.9, 0.92, 1.0), roughness=0.7),
    "Garage": get_or_create_material("Mat_Garage", (0.88, 0.88, 0.9, 1.0), roughness=0.65),
    "GarageDoor": get_or_create_material("Mat_GarageDoor", (0.3, 0.3, 0.32, 1.0), roughness=0.7),
    "Dormer": get_or_create_material("Mat_Dormer", (0.92, 0.92, 0.94, 1.0), roughness=0.7),
    "Plinth": get_or_create_material("Mat_Plinth", (0.4, 0.4, 0.42, 1.0), roughness=0.9),
    "Band": get_or_create_material("Mat_Band", (0.85, 0.85, 0.87, 1.0), roughness=0.6),
    "Parapet": get_or_create_material("Mat_Parapet", (0.85, 0.85, 0.88, 1.0), roughness=0.7),
    "Gutter": get_or_create_material("Mat_Gutter", (0.2, 0.2, 0.22, 1.0), roughness=0.3, metallic=0.8),
    "Walkway": get_or_create_material("Mat_Walkway", (0.5, 0.5, 0.5, 1.0), roughness=0.95),
    "Landscape": get_or_create_material("Mat_Landscape", (0.18, 0.28, 0.18, 1.0), roughness=0.95),
    "Secondary": get_or_create_material("Mat_Secondary", (0.9, 0.9, 0.92, 1.0), roughness=0.7),
}

texture_sets = specs.get("texture_sets", {}) if isinstance(specs, dict) else {}
textures_applied = set()
for mat_key, tex_key in {
    "Wall": "wall",
    "Roof": "roof",
    "Ground": "ground",
    "Driveway": "driveway",
    "Walkway": "walkway",
}.items():
    tex_info = texture_sets.get(tex_key)
    if tex_info and apply_pbr_textures(materials[mat_key], tex_info):
        textures_applied.add(mat_key)

if "Wall" not in textures_applied:
    apply_noise_color(materials["Wall"], (0.88, 0.88, 0.88, 1.0), (0.95, 0.95, 0.95, 1.0), scale=12.0)
    apply_bump(materials["Wall"], scale=35.0, strength=0.2)
if "Roof" not in textures_applied:
    apply_noise_color(materials["Roof"], (0.25, 0.15, 0.08, 1.0), (0.38, 0.24, 0.14, 1.0), scale=18.0)
    apply_bump(materials["Roof"], scale=50.0, strength=0.25)
if "Ground" not in textures_applied:
    apply_noise_color(materials["Ground"], (0.12, 0.22, 0.12, 1.0), (0.25, 0.35, 0.2, 1.0), scale=8.0)
if "Driveway" not in textures_applied:
    apply_noise_color(materials["Driveway"], (0.25, 0.25, 0.25, 1.0), (0.45, 0.45, 0.45, 1.0), scale=25.0)
    apply_bump(materials["Driveway"], scale=15.0, strength=0.15)

# material overrides from specs
mat_specs = specs.get("materials", {}) if isinstance(specs, dict) else {}
wall_mat = (mat_specs.get("wall") or "stucco").lower()
roof_mat = (mat_specs.get("roof") or "shingle").lower()
trim_mat = (mat_specs.get("trim") or "white").lower()
window_mat = (mat_specs.get("window") or "clear").lower()

def set_material_color(mat, color):
    if not mat or not mat.use_nodes:
        return
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color

if "Wall" not in textures_applied:
    if wall_mat == "brick":
        set_material_color(materials["Wall"], (0.55, 0.2, 0.18, 1.0))
    elif wall_mat == "wood":
        set_material_color(materials["Wall"], (0.5, 0.35, 0.2, 1.0))
    else:
        set_material_color(materials["Wall"], (0.92, 0.92, 0.92, 1.0))

if "Roof" not in textures_applied:
    if roof_mat == "metal":
        set_material_color(materials["Roof"], (0.35, 0.4, 0.45, 1.0))
    elif roof_mat == "tile":
        set_material_color(materials["Roof"], (0.55, 0.25, 0.15, 1.0))
    else:
        set_material_color(materials["Roof"], (0.28, 0.2, 0.15, 1.0))

if trim_mat == "black":
    set_material_color(materials["Trim"], (0.1, 0.1, 0.12, 1.0))
elif trim_mat == "wood":
    set_material_color(materials["Trim"], (0.5, 0.35, 0.2, 1.0))
else:
    set_material_color(materials["Trim"], (0.9, 0.9, 0.92, 1.0))

if window_mat == "tinted":
    set_material_color(materials["Window"], (0.3, 0.4, 0.45, 1.0))

for obj in bpy.context.scene.objects:
    if obj.type != 'MESH':
        continue
    name = obj.name
    if name.startswith("Wall"):
        mat = materials["Wall"]
    elif name.startswith("Roof"):
        mat = materials["Roof"]
    elif name.startswith("Floor"):
        mat = materials["Floor"]
    elif name.startswith("Ceiling"):
        mat = materials["Ceiling"]
    elif name.startswith("Door"):
        mat = materials["Door"]
    elif name.startswith("Window"):
        mat = materials["Window"]
    elif name.startswith("Ground"):
        mat = materials["Ground"]
    elif name.startswith("Trim"):
        mat = materials["Trim"]
    elif name.startswith("Plinth"):
        mat = materials["Plinth"]
    elif name.startswith("Trim_Band"):
        mat = materials["Band"]
    elif name.startswith("Parapet"):
        mat = materials["Parapet"]
    elif name.startswith("Gutter") or name.startswith("Downspout"):
        mat = materials["Gutter"]
    elif name.startswith("Driveway"):
        mat = materials["Driveway"]
    elif name.startswith("Walkway"):
        mat = materials["Walkway"]
    elif name.startswith("Landscape_Bed"):
        mat = materials["Landscape"]
    elif name.startswith("Tree_Trunk"):
        mat = materials["TreeTrunk"]
    elif name.startswith("Tree_Leaf"):
        mat = materials["TreeLeaf"]
    elif name.startswith("Porch"):
        mat = materials["Porch"]
    elif name.startswith("Porch_Column"):
        mat = materials["Column"]
    elif name.startswith("Porch_Step"):
        mat = materials["Step"]
    elif name.startswith("Gable"):
        mat = materials["Gable"]
    elif name.startswith("Garage_Door"):
        mat = materials["GarageDoor"]
    elif name.startswith("Garage"):
        mat = materials["Garage"]
    elif name.startswith("Dormer"):
        mat = materials["Dormer"]
    elif name.startswith("Volume_Secondary"):
        mat = materials["Secondary"]
    else:
        mat = materials["Room"]
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)

# set render path

# Set up consistent four-view rendering (front, rear, left, right)
bpy.context.scene.render.engine = 'CYCLES'
bpy.context.scene.render.resolution_x = 3840  # 4K UHD width
bpy.context.scene.render.resolution_y = 2160  # 4K UHD height
bpy.context.scene.cycles.samples = 96
bpy.context.scene.cycles.use_denoising = True
bpy.context.scene.view_settings.exposure = 0.8

# world light (HDRI if provided, else procedural sky)
world = bpy.data.worlds.get("World")
if world is not None:
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    output = nodes.new(type='ShaderNodeOutputWorld')
    hdr_path = specs.get("hdri_path") if isinstance(specs, dict) else None
    if hdr_path and os.path.exists(hdr_path):
        env = nodes.new(type='ShaderNodeTexEnvironment')
        env.image = bpy.data.images.load(hdr_path)
        bg = nodes.new(type='ShaderNodeBackground')
        bg.inputs[1].default_value = 1.0
        links.new(env.outputs['Color'], bg.inputs['Color'])
        links.new(bg.outputs['Background'], output.inputs['Surface'])
    else:
        bg = nodes.new(type='ShaderNodeBackground')
        sky = nodes.new(type='ShaderNodeTexSky')
        sky.sun_elevation = math.radians(35)
        sky.air_density = 1.0
        bg.inputs[1].default_value = 1.0
        links.new(sky.outputs['Color'], bg.inputs['Color'])
        links.new(bg.outputs['Background'], output.inputs['Surface'])

# lighting
bpy.ops.object.light_add(type='SUN', location=(10, 10, 20))
sun = bpy.context.object
sun.data.energy = 3.5
sun.data.angle = math.radians(2.0)

bpy.ops.object.light_add(type='AREA', location=(0, 0, 12))
area = bpy.context.object
area.data.energy = 300.0
area.data.size = 12.0

# Camera positions for four consistent views
def set_camera(angle_deg, distance, height):
    az = math.radians(angle_deg)
    x = center[0] + distance * math.cos(az)
    y = center[1] + distance * math.sin(az)
    z = center[2] + height
    cam_ob.location = (x, y, z)
    direction = Vector(center) - cam_ob.location
    cam_ob.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()

view_configs = [
    ("front", 0),
    ("right", 90),
    ("rear", 180),
    ("left", 270),
]
distance = max(max_dim * 2.5, 12)
height = distance * 0.6
cam.lens = 28
base, ext = os.path.splitext(__OUTFILE__)
for view_name, angle in view_configs:
    set_camera(angle, distance, height)
    bpy.context.scene.render.filepath = base + f"_{view_name}" + (ext if ext else ".png")
    bpy.ops.render.render(write_still=True)

def _resolve_blender_exec():
    env_exec = os.environ.get("BLENDER_EXEC")
    if env_exec:
        return env_exec

    which_exec = shutil.which(BLENDER_EXEC)
    if which_exec:
        return which_exec

    # common Windows install locations
    base_dir = r"C:\Program Files\Blender Foundation"
    if os.path.isdir(base_dir):
        for entry in sorted(os.listdir(base_dir), reverse=True):
            candidate = os.path.join(base_dir, entry, "blender.exe")
            if os.path.isfile(candidate):
                return candidate

    return None


def render_glb_with_blender(infile="outputs/3d_models/house.glb", outfile="outputs/renders/house_render.png", specs_path="outputs/specs.json", identity_path="outputs/house_identity.json"):
    blender_exec = _resolve_blender_exec()
    if not blender_exec:
        raise FileNotFoundError(
            "Blender executable not found. Install Blender, add it to PATH, or set BLENDER_EXEC env var."
        )
    # create a temporary script
    script_path = "temp_blender_script.py"
    script_text = BLENDER_SCRIPT.replace("__INFILE__", repr(os.path.abspath(infile)))
    script_text = script_text.replace("__OUTFILE__", repr(os.path.abspath(outfile)))
    script_text = script_text.replace("__SPECS__", repr(os.path.abspath(specs_path)))
    script_text = script_text.replace("__IDENTITY__", repr(os.path.abspath(identity_path)))
    with open(script_path, "w") as f:
        f.write(script_text)
    # call blender in background
    cmd = [blender_exec, "-b", "--python", script_path]
    print("Running Blender:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"Rendered image to {outfile}")
    # cleanup
    os.remove(script_path)

if __name__ == "__main__":
    render_glb_with_blender()

"""
