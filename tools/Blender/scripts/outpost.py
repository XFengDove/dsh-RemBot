# -*- coding: utf-8 -*-
"""末日废土哨站 —— 从零生成完整场景（可直接打开使用）。

    blender -b -P outpost.py

输出：
    outpost.blend
    renders/outpost_hero.png / wide.png / closeup.png / top.png
"""
import math
import os
import random

import bpy
from mathutils import Vector

OUT = os.path.dirname(os.path.abspath(__file__))
REN = os.path.join(OUT, "renders")
os.makedirs(REN, exist_ok=True)
random.seed(20770207)

PARTS = []
MATS = {}


# ---------------- 材质 ----------------
def _bsdf(m):
    return next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def simple_mat(name, color, rough=0.8, metal=0.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    b = _bsdf(m)
    if b:
        b.inputs["Base Color"].default_value = (*color, 1.0)
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*color, 1.0)
    MATS[name] = m
    return m


def rust_mat(name, base, rust=(0.26, 0.14, 0.08), rough=0.8, metal=0.45, scale=5.0):
    """带锈迹噪声的金属。"""
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    nt = m.node_tree
    b = _bsdf(m)
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = 6.0
    tex.inputs["Roughness"].default_value = 0.7
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.45
    ramp.color_ramp.elements[0].color = (*base, 1.0)
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = (*rust, 1.0)
    nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    if b:
        nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*base, 1.0)
    MATS[name] = m
    return m


def mats():
    return dict(
        sand=simple_mat("沙土", (0.34, 0.27, 0.18), 0.95),
        sand2=simple_mat("沙土_深", (0.26, 0.21, 0.15), 0.95),
        concrete=simple_mat("混凝土", (0.40, 0.38, 0.35), 0.9),
        concrete2=simple_mat("混凝土_旧", (0.30, 0.28, 0.26), 0.95),
        metal=rust_mat("锈铁", (0.34, 0.33, 0.32)),
        metal2=rust_mat("锈铁_深", (0.26, 0.25, 0.24), (0.24, 0.09, 0.04), 0.8, 0.5, 12.0),
        wood=simple_mat("风化木", (0.34, 0.26, 0.18), 0.92),
        wood2=simple_mat("深色木", (0.22, 0.17, 0.12), 0.95),
        canvas=simple_mat("旧帆布", (0.40, 0.35, 0.26), 0.95),
        sandbag=simple_mat("沙袋", (0.36, 0.32, 0.24), 0.95),
        dark=simple_mat("暗部", (0.05, 0.05, 0.05), 0.9),
        glass=simple_mat("脏玻璃", (0.12, 0.15, 0.14), 0.25, 0.4),
        solar=simple_mat("太阳能板", (0.05, 0.08, 0.14), 0.15, 0.7),
        fire=simple_mat("火焰", (1.0, 0.35, 0.05), 0.4),
        tires=simple_mat("橡胶", (0.06, 0.06, 0.06), 0.95),
        paint=simple_mat("掉漆红", (0.38, 0.10, 0.08), 0.85),
    )


# ---------------- 基础几何 ----------------
def _add(ob, coll=None):
    # 用数据 API 创建的对象必须手动链接进场景，否则不参与渲染
    target = coll or bpy.context.scene.collection
    try:
        if ob.name not in target.objects:
            target.objects.link(ob)
    except RuntimeError:
        pass
    PARTS.append(ob)
    return ob


def box(name, size, loc, mat=None, rot=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    vs = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
    fs = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata([(a * size[0], b * size[1], c * size[2]) for a, b, c in vs], [], fs)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = rot
    if mat:
        ob.data.materials.append(mat)
    return _add(ob)


def cyl(name, r, depth, loc, mat=None, verts=24, rot=(0, 0, 0), r2=None):
    r2 = r if r2 is None else r2
    me = bpy.data.meshes.new(name)
    vs, fs = [], []
    for i in range(verts):
        a = 2 * math.pi * i / verts
        vs.append((r * math.cos(a), r * math.sin(a), -depth / 2))
        vs.append((r2 * math.cos(a), r2 * math.sin(a), depth / 2))
    for i in range(verts):
        j = (i + 1) % verts
        fs.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
    fs.append(tuple(range(0, 2 * verts, 2))[::-1])
    fs.append(tuple(range(1, 2 * verts, 2)))
    me.from_pydata(vs, [], fs)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.rotation_euler = rot
    if mat:
        ob.data.materials.append(mat)
    return _add(ob)


def sphere(name, r, loc, mat=None, scale=(1, 1, 1), segments=20):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc, segments=segments, ring_count=segments // 2)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = scale
    if mat:
        ob.data.materials.append(mat)
    return _add(ob)


def arch(name, r, length, loc, mat=None, segs=18):
    me = bpy.data.meshes.new(name)
    vs, fs = [], []
    for i in range(segs + 1):
        a = math.pi * i / segs
        x, z = r * math.cos(a), r * math.sin(a)
        vs.append((x, -length / 2, z))
        vs.append((x, length / 2, z))
    for i in range(segs):
        fs.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
    # 两端封口
    fs.append(tuple(range(0, 2 * (segs + 1), 2)))
    fs.append(tuple(range(1, 2 * (segs + 1), 2))[::-1])
    me.from_pydata(vs, [], fs)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    if mat:
        ob.data.materials.append(mat)
    return _add(ob)


def text_mesh(name, body, size, loc, rot=(0, 0, 0), mat=None):
    bpy.ops.object.text_add(location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.data.body = body
    ob.data.size = size
    ob.data.extrude = 0.02
    ob.rotation_euler = rot
    bpy.ops.object.convert(target="MESH")
    ob = bpy.context.active_object
    if mat:
        ob.data.materials.append(mat)
    return _add(ob)


# ---------------- 场景 ----------------
def ground(c):
    bpy.ops.mesh.primitive_plane_add(size=260, location=(0, 0, 0))
    g = bpy.context.active_object
    g.name = "废土地面"
    g.data.materials.append(c["sand"])
    # 细分 + 置换做出起伏
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.subdivide(number_cuts=120)
    bpy.ops.object.mode_set(mode="OBJECT")
    tex = bpy.data.textures.new("dune", type="CLOUDS")
    tex.noise_scale = 18
    disp = g.modifiers.new("disp", "DISPLACE")
    disp.texture = tex
    disp.strength = 1.6
    disp.mid_level = 0.5
    bpy.ops.object.modifier_apply(modifier=disp.name)
    # 再叠一层细碎
    tex2 = bpy.data.textures.new("grit", type="CLOUDS")
    tex2.noise_scale = 3
    disp2 = g.modifiers.new("disp2", "DISPLACE")
    disp2.texture = tex2
    disp2.strength = 0.18
    bpy.ops.object.modifier_apply(modifier=disp2.name)
    return g


def outpost(c):
    P = c
    base_z = 0.15

    # 混凝土基座
    box("基座", (16, 13, 0.5), (0, 0, base_z), P["concrete"])
    box("基座边", (16.6, 13.6, 0.18), (0, 0, 0.05), P["concrete2"])

    # ---- 哨塔 ----
    tx, ty = -3.5, -2.0
    leg_h = 5.2
    for dx, dy in ((-2.0, -2.0), (2.0, -2.0), (-2.0, 2.0), (2.0, 2.0)):
        box(f"塔腿{dx}{dy}", (0.32, 0.32, leg_h), (tx + dx, ty + dy, base_z + leg_h / 2), P["wood2"])
    # 斜撑
    for dx in (-2, 2):
        box(f"塔斜撑{dx}", (0.16, 4.6, 0.16), (tx + dx, ty, base_z + leg_h * 0.55), P["wood"],
            rot=(math.radians(38), 0, 0))
    # 平台
    box("塔平台", (5.2, 5.2, 0.3), (tx, ty, base_z + leg_h), P["wood"])
    # 小屋
    cab_h = 2.7
    box("塔屋", (4.4, 4.4, cab_h), (tx, ty, base_z + leg_h + cab_h / 2 + 0.15), P["metal"])
    # 屋顶（双坡）
    roof_top = base_z + leg_h + cab_h + 0.18
    for sd in (-1, 1):
        box(f"塔顶{sd}", (5.2, 2.75, 0.12), (tx, ty + sd * 1.28, roof_top + 0.32), P["metal2"],
            rot=(math.radians(-sd * 21), 0, 0))
    # 窗
    box("塔窗", (1.6, 0.12, 0.9), (tx, ty - 2.25, base_z + leg_h + 1.9), P["glass"])
    box("塔窗框", (1.9, 0.2, 1.15), (tx, ty - 2.3, base_z + leg_h + 1.9), P["wood2"])
    # 围栏板（女儿墙）
    for s, rot in ((-2.35, 0), (2.35, 0), (-2.35, math.pi / 2), (2.35, math.pi / 2)):
        if abs(s) > 2:
            pass
    box("塔前围板", (5.2, 0.14, 1.0), (tx, ty - 2.5, base_z + leg_h + 0.65), P["wood"])
    # 梯子
    for dx in (-0.5, 0.5):
        box(f"梯梁{dx}", (0.1, 0.1, leg_h + 1), (tx + 2.4 + dx, ty - 2.0, base_z + (leg_h + 1) / 2), P["metal2"])
    for i in range(9):
        box(f"梯级{i}", (1.0, 0.09, 0.09), (tx + 2.4, ty - 2.0, base_z + 0.7 + i * 0.55), P["metal2"])

    # 天线 + 雷达
    cyl("天线杆", 0.06, 3.0, (tx + 1.6, ty + 1.6, base_z + leg_h + cab_h + 1.8), P["metal2"], 10)
    cyl("雷达座", 0.3, 0.25, (tx + 1.6, ty + 1.6, base_z + leg_h + cab_h + 0.4), P["metal2"], 16)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.8, location=(tx + 1.6, ty + 1.6,
                                                              base_z + leg_h + cab_h + 1.1))
    dish = bpy.context.active_object
    dish.name = "雷达"
    dish.scale = (1, 1, 0.45)
    dish.rotation_euler = (math.radians(-30), 0, math.radians(20))
    dish.data.materials.append(P["metal"])
    for p in dish.data.polygons:
        if p.center.z < 0:
            p.select = False
    PARTS.append(dish)

    # ---- 集装箱（住所）----
    cx, cy = 3.4, -3.6
    box("集装箱", (6.2, 2.5, 2.6), (cx, cy, base_z + 1.3), P["metal"])
    for i in range(11):
        box(f"箱肋{i}", (0.08, 2.54, 2.3), (cx - 2.9 + i * 0.58, cy, base_z + 1.3), P["metal2"])
    box("箱门", (0.1, 2.0, 2.0), (cx - 3.15, cy, base_z + 1.2), P["metal2"])
    box("箱门把手", (0.06, 0.06, 0.8), (cx - 3.2, cy - 0.8, base_z + 1.2), P["metal2"])
    # 门口台阶
    box("箱台阶", (1.6, 1.0, 0.35), (cx - 3.9, cy, base_z + 0.18), P["wood"])

    # ---- 帐篷 ----
    bpy.ops.mesh.primitive_cone_add(vertices=4, radius1=2.2, depth=2.2, location=(6.2, 2.6, base_z + 1.1))
    tent = bpy.context.active_object
    tent.name = "帐篷"
    tent.rotation_euler = (0, 0, math.radians(45))
    tent.scale = (1.1, 1.0, 1.0)
    tent.data.materials.append(P["canvas"])
    PARTS.append(tent)
    cyl("帐篷杆", 0.04, 2.6, (6.2, 2.6, base_z + 2.4), P["wood2"], 8)

    # ---- 沙袋墙（半围）----
    bag_positions = []
    for i in range(9):
        x = -6.5 + i * 1.55
        bag_positions.append((x, 5.6))
    for i in range(7):
        y = 4.2 - i * 1.5
        bag_positions.append((-7.2, y))
    for i, (bx, by) in enumerate(bag_positions):
        for row in range(2):
            sphere(f"沙袋{i}_{row}", 0.5, (bx + (0.22 if row else 0), by, base_z + 0.26 + row * 0.46),
                   P["sandbag"], scale=(1.15, 0.8, 0.55), segments=16)

    # ---- 铁丝网 ----
    posts = [(-8, -6), (-8, 0), (-8, 6), (-4, -7), (2, -7), (8, -7)]
    for i, (px, py) in enumerate(posts):
        box(f"网柱{i}", (0.12, 0.12, 2.1), (px, py, base_z + 1.05), P["metal2"])
    wire_pairs = [((-8, -6), (-8, 0)), ((-8, 0), (-8, 6)), ((-8, 6), (-4, 7)),
                  ((-4, -7), (2, -7)), ((2, -7), (8, -7)), ((-8, -6), (-4, -7))]
    for i, ((x1, y1), (x2, y2)) in enumerate(wire_pairs):
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        length = math.hypot(x2 - x1, y2 - y1)
        ang = math.atan2(y2 - y1, x2 - x1)
        for k in range(3):
            cyl(f"铁线{i}_{k}", 0.02, length, (mx, my, base_z + 0.6 + k * 0.55), P["metal2"], 6,
                rot=(0, math.pi / 2, ang))

    # ---- 油桶 ----
    for i, (bx, by, tipped) in enumerate([(-1.5, 4.2, False), (-0.6, 4.6, False),
                                          (0.4, 4.3, True), (5.0, 0.4, False)]):
        if tipped:
            cyl(f"油桶{i}", 0.42, 1.1, (bx, by, base_z + 0.42), P["metal"], 20,
                rot=(0, math.pi / 2, math.radians(30)))
        else:
            cyl(f"油桶{i}", 0.42, 1.1, (bx, by, base_z + 0.55), P["metal"], 20)
            cyl(f"桶箍{i}a", 0.44, 0.08, (bx, by, base_z + 0.35), P["metal2"], 20)
            cyl(f"桶箍{i}b", 0.44, 0.08, (bx, by, base_z + 0.78), P["metal2"], 20)

    # ---- 发电机 ----
    gx, gy = 1.6, 2.2
    box("发电机", (2.2, 1.2, 1.1), (gx, gy, base_z + 0.55), P["paint"])
    box("发电机顶", (2.3, 1.3, 0.12), (gx, gy, base_z + 1.12), P["metal2"])
    cyl("排气管", 0.09, 1.4, (gx + 0.9, gy + 0.4, base_z + 1.7), P["metal2"], 12)
    cyl("油罐", 0.3, 0.9, (gx - 1.4, gy, base_z + 0.45), P["metal"], 16)

    # ---- 太阳能板 ----
    for i, (px, py) in enumerate([(-6.0, -3.0), (-6.0, -0.6)]):
        box(f"板架{i}", (1.9, 1.3, 0.08), (px, py, base_z + 1.0), P["metal2"],
            rot=(math.radians(-38), 0, 0))
        box(f"太阳能板{i}", (1.8, 1.2, 0.06), (px, py, base_z + 1.08), P["solar"],
            rot=(math.radians(-38), 0, 0))
        for dx in (-0.7, 0.7):
            box(f"板腿{i}{dx}", (0.08, 0.08, 1.0), (px + dx, py + 0.3, base_z + 0.5), P["metal2"])

    # ---- 水塔 ----
    wx, wy = 6.4, -0.6
    for dx, dy in ((-0.6, -0.6), (0.6, -0.6), (-0.6, 0.6), (0.6, 0.6)):
        box(f"水塔腿{dx}{dy}", (0.12, 0.12, 2.0), (wx + dx, wy + dy, base_z + 1.0), P["metal2"])
    cyl("水罐", 0.95, 1.6, (wx, wy, base_z + 2.7), P["metal"], 20)
    cyl("水罐顶", 0.95, 0.15, (wx, wy, base_z + 3.5), P["metal2"], 20)

    # ---- 篝火 ----
    fx, fy = -1.0, -5.2
    for i in range(9):
        a = 2 * math.pi * i / 9
        sphere(f"火石{i}", 0.2, (fx + 0.75 * math.cos(a), fy + 0.75 * math.sin(a), base_z + 0.16),
               P["concrete2"], scale=(1, 1, 0.7), segments=10)
    for i in range(4):
        a = math.pi * i / 4
        box(f"柴{i}", (1.0, 0.09, 0.09), (fx, fy, base_z + 0.22), P["wood2"],
            rot=(0, 0, a))
    bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=0.35, depth=0.9, location=(fx, fy, base_z + 0.55))
    flame = bpy.context.active_object
    flame.name = "火焰"
    flame.data.materials.append(P["fire"])
    PARTS.append(flame)
    bpy.ops.object.light_add(type="POINT", location=(fx, fy, base_z + 0.8))
    fl = bpy.context.active_object
    fl.name = "火光"
    fl.data.color = (1.0, 0.45, 0.15)
    fl.data.energy = 220
    fl.data.shadow_soft_size = 0.6

    # ---- 招牌 ----
    box("招牌柱a", (0.14, 0.14, 2.4), (-8.6, -7.6, base_z + 1.2), P["wood2"])
    box("招牌柱b", (0.14, 0.14, 2.4), (-6.4, -7.6, base_z + 1.2), P["wood2"])
    box("招牌板", (2.4, 0.12, 0.9), (-7.5, -7.6, base_z + 2.45), P["wood"])
    text_mesh("招牌字", "OUTPOST 7", 0.42, (-8.45, -7.85, base_z + 2.2),
              rot=(math.radians(90), 0, 0), mat=P["paint"])

    # ---- 残骸车辆 ----
    vx, vy = -4.6, 6.6
    box("车体", (3.4, 1.8, 1.1), (vx, vy, base_z + 0.75), P["metal2"], rot=(0, 0, math.radians(18)))
    box("车厢", (1.6, 1.6, 0.7), (vx + 0.9, vy - 0.1, base_z + 1.5), P["metal"], rot=(0, 0, math.radians(18)))
    for i, (dx, dy) in enumerate([(-1.2, -0.95), (1.2, -0.95), (-1.2, 0.95), (1.2, 0.95)]):
        cyl(f"车轮{i}", 0.42, 0.28, (vx + dx, vy + dy, base_z + 0.42), P["tires"], 18,
            rot=(math.pi / 2, 0, math.radians(18)))

    # ---- 碎石与杂物 ----
    for i in range(38):
        a = random.uniform(0, 2 * math.pi)
        r = random.uniform(7.5, 26)
        sx, sy = r * math.cos(a), r * math.sin(a)
        s = random.uniform(0.15, 0.75)
        box(f"碎石{i}", (s, s * random.uniform(0.6, 1.2), s * 0.55),
            (sx, sy, base_z + s * 0.2), P["concrete2"] if i % 4 else P["sand2"],
            rot=(0, 0, random.uniform(0, 3.14)))
    # 散落木板
    for i in range(12):
        a = random.uniform(0, 2 * math.pi)
        r = random.uniform(9, 20)
        box(f"木板{i}", (2.2, 0.22, 0.07), (r * math.cos(a), r * math.sin(a), base_z + 0.12),
            P["wood"], rot=(0, 0, random.uniform(0, 3.14)))

    # ---- 远处的岩块 ----
    for i in range(14):
        a = random.uniform(0, 2 * math.pi)
        r = random.uniform(45, 90)
        s = random.uniform(2.5, 8.0)
        sphere(f"岩块{i}", 1.0, (r * math.cos(a), r * math.sin(a), s * 0.15),
               P["sand2"], scale=(s, s * 0.8, s * 0.5), segments=14)


def camera_and_light(c):
    scene = bpy.context.scene

    # 低角度暖阳
    bpy.ops.object.light_add(type="SUN", location=(-60, 80, 40))
    sun = bpy.context.active_object
    sun.name = "夕阳"
    sun.data.energy = 7.0
    sun.data.color = (1.0, 0.62, 0.34)
    sun.data.angle = math.radians(1.5)
    sun.rotation_euler = (math.radians(82), 0, math.radians(60))

    # 天空补光
    bpy.ops.object.light_add(type="AREA", location=(20, -40, 25))
    fill = bpy.context.active_object
    fill.name = "天光"
    fill.data.energy = 900
    fill.data.size = 40
    fill.data.color = (0.45, 0.52, 0.66)
    fill.rotation_euler = (math.radians(50), 0, math.radians(-40))

    # 世界：沙尘天空
    world = bpy.data.worlds.new("沙尘天空")
    scene.world = world
    if hasattr(world, "use_nodes"):
        world.use_nodes = True
    bg = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if bg:
        bg.inputs[0].default_value = (0.46, 0.40, 0.34, 1.0)
        bg.inputs[1].default_value = 0.75

    # 相机
    bpy.ops.object.camera_add(location=(26, -30, 9))
    cam = bpy.context.active_object
    cam.name = "Camera"
    cam.data.lens = 35
    scene.camera = cam

    # 渲染设置
    scene.render.engine = pick_engine()
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 900
    scene.render.image_settings.file_format = "PNG"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    if "EEVEE" in scene.render.engine:
        ee = scene.eevee
        for attr, val in (("taa_render_samples", 48), ("use_gtao", True), ("use_raytracing", True)):
            if hasattr(ee, attr):
                try:
                    setattr(ee, attr, val)
                except Exception:
                    pass
    return cam


def pick_engine():
    try:
        engines = [i.identifier for i in bpy.context.scene.render.bl_rna.properties["engine"].enum_items]
    except Exception:
        engines = []
    for cand in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        if cand in engines:
            return cand
    return "BLENDER_WORKBENCH"


def look(cam, loc, target, lens=35):
    cam.location = Vector(loc)
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    cam.data.lens = lens


def render_all(cam):
    scene = bpy.context.scene
    shots = {
        "hero": ((18, -23, 4.2), (0, 0, 3.4), 28),
        "wide": ((42, -54, 18), (0, 0, 2.5), 30),
        "closeup": ((9, -13, 3.6), (-3.5, -2.0, 5.0), 45),
        "top": ((5, -15, 30), (0, 0, 2), 36),
    }
    for name, (loc, tgt, lens) in shots.items():
        look(cam, loc, tgt, lens)
        scene.render.filepath = os.path.join(REN, f"outpost_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("RENDER OK", name)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    c = mats()
    ground(c)
    outpost(c)
    cam = camera_and_light(c)
    blend = os.path.join(OUT, "outpost.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print("SAVED", blend)
    render_all(cam)
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    print("DONE objects=", len(bpy.data.objects))


if __name__ == "__main__":
    main()
