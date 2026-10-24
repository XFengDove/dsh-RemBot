# -*- coding: utf-8 -*-
r"""人民大会堂 v3 — 真实比例版（336 × 206 × 46.5 m）。

在 Blender 里执行：
    exec(open(r"scripts\great_hall_v3.py").read())  # 路径按解压位置调整
    build_v3()
"""
import math

import bpy
from mathutils import Vector

# ================= 真实尺寸（米） =================
L = 336.0          # 南北长（这里用 X 轴）
D = 206.0          # 东西宽
TOTAL_H = 46.5     # 最高点
PODIUM_H = 6.0     # 台基
BODY_H = 34.0      # 主体
ROOF_Z = PODIUM_H + BODY_H          # 40
COL_H = 25.0       # 巨柱高
COL_R = 1.85       # 柱半径
N_COL = 12
COL_SPAN = 150.0
FRONT_Y = -D / 2                     # -103
PORCH_Y = FRONT_Y - 9.0              # 柱中心线 -112

MATS = {}
PARTS = []


# ================= 工具 =================
def M(name, color, rough=0.55, metal=0.0):
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if hasattr(m, "use_nodes"):
        m.use_nodes = True
    bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Metallic"].default_value = metal
    m.diffuse_color = (*color, 1.0)
    MATS[name] = m
    return m


def _mats():
    return dict(
        stone=M("石材_米白", (0.82, 0.78, 0.68), 0.55),
        stone2=M("石材_浅灰", (0.70, 0.67, 0.60), 0.6),
        stone3=M("石材_深灰", (0.46, 0.44, 0.41), 0.65),
        trim=M("石材_线脚", (0.88, 0.85, 0.76), 0.5),
        bronze=M("青铜", (0.20, 0.13, 0.07), 0.38, 0.85),
        bronze2=M("青铜_亮", (0.34, 0.24, 0.12), 0.3, 0.9),
        glass=M("玻璃", (0.08, 0.12, 0.17), 0.10, 0.45),
        roofm=M("屋面", (0.56, 0.54, 0.50), 0.7),
        red=M("红旗", (0.62, 0.05, 0.05), 0.8),
        plaza=M("广场铺装", (0.62, 0.61, 0.58), 0.75),
    )


def _add(ob, coll, join=True):
    if coll and ob.name not in coll.objects:
        coll.objects.link(ob)
    if join:
        PARTS.append(ob)
    return ob


def box(coll, name, size, loc, mat=None, join=True):
    me = bpy.data.meshes.new(name)
    vs = [(x, y, z) for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)]
    fs = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata([(a * size[0], b * size[1], c * size[2]) for a, b, c in vs], [], fs)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    if mat:
        ob.data.materials.append(mat)
    return _add(ob, coll, join)


def cyl(coll, name, radius, depth, loc, mat=None, verts=48, r2=None, join=True):
    r2 = radius if r2 is None else r2
    me = bpy.data.meshes.new(name)
    vs, fs = [], []
    for i in range(verts):
        a = 2 * math.pi * i / verts
        vs.append((radius * math.cos(a), radius * math.sin(a), -depth / 2))
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
    if mat:
        ob.data.materials.append(mat)
    return _add(ob, coll, join)


def fluted_column(coll, name, x, y, z0, height, radius, mat, flutes=24, groove=0.05, taper=0.90):
    """带凹槽 + 收分的巨柱。"""
    me = bpy.data.meshes.new(name)
    n = flutes * 2
    vs, fs = [], []
    for i in range(n):
        a = 2 * math.pi * i / n
        r = radius if i % 2 == 0 else radius * (1 - groove)
        vs.append((r * math.cos(a), r * math.sin(a), 0.0))
        rt = r * taper
        vs.append((rt * math.cos(a), rt * math.sin(a), height))
    for i in range(n):
        j = (i + 1) % n
        fs.append((2 * i, 2 * j, 2 * j + 1, 2 * i + 1))
    fs.append(tuple(range(0, 2 * n, 2))[::-1])
    fs.append(tuple(range(1, 2 * n, 2)))
    me.from_pydata(vs, [], fs)
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.location = (x, y, z0)
    ob.data.materials.append(mat)
    _add(ob, coll)
    return ob


def clean_old(coll_name="人民大会堂"):
    for ob in list(bpy.data.objects):
        if ob.name.startswith(coll_name) or ob.name.startswith("广场"):
            bpy.data.objects.remove(ob, do_unlink=True)
    old = bpy.data.collections.get(coll_name)
    if old:
        bpy.data.collections.remove(old)


# ================= 建模 =================
def build_v3():
    clean_old()
    c = _mats()
    coll = bpy.data.collections.new("人民大会堂")
    bpy.context.scene.collection.children.link(coll)

    # ---------- 广场 ----------
    box(coll, "广场", (760, 420, 0.4), (0, -210, -0.2), c["plaza"], join=False)

    # ---------- 台基（三级） ----------
    box(coll, "台基1", (L + 56, D + 52, 2.2), (0, 0, 1.1), c["stone3"])
    box(coll, "台基2", (L + 42, D + 38, 1.9), (0, 0, 3.15), c["stone2"])
    box(coll, "台基3", (L + 28, D + 24, 1.9), (0, 0, 5.05), c["stone"])
    for nm, sz, z in (("台基线1", (L + 57, D + 53, 0.35), 2.2),
                      ("台基线2", (L + 43, D + 39, 0.3), 4.05),
                      ("台基线3", (L + 29, D + 25, 0.3), 6.0)):
        box(coll, nm, sz, (0, 0, z), c["trim"])

    # ---------- 正面大台阶 ----------
    rise, run = 0.5, 1.6
    plat_front = FRONT_Y - 24
    for i in range(12):
        z_top = PODIUM_H - rise * (i + 1)
        y = plat_front - run * i - run / 2
        box(coll, f"台阶{i}", (196, run, z_top), (0, y, z_top / 2),
            c["stone2"] if i % 2 else c["stone"])
    for sx in (-1, 1):
        box(coll, f"台阶挡墙{sx}", (5, 30, 8), (sx * 112, plat_front - 11, 4.0), c["stone3"])

    # ---------- 门廊平台 ----------
    box(coll, "门廊平台", (COL_SPAN + 60, 34, PODIUM_H), (0, PORCH_Y + 4, PODIUM_H / 2), c["stone2"])
    box(coll, "门廊线脚", (COL_SPAN + 62, 36, 0.4), (0, PORCH_Y + 4, PODIUM_H - 0.2), c["trim"])

    # ---------- 12 根巨柱 ----------
    for i in range(N_COL):
        x = -COL_SPAN / 2 + COL_SPAN * i / (N_COL - 1)
        # 柱础
        box(coll, f"柱础{i}", (4.6, 4.6, 0.8), (x, PORCH_Y, PODIUM_H + 0.4), c["stone3"])
        cyl(coll, f"柱础锥{i}", 2.6, 1.9, (x, PORCH_Y, PODIUM_H + 1.35), c["stone2"], 48, r2=2.0)
        # 柱身（凹槽 + 收分）
        fluted_column(coll, f"柱身{i}", x, PORCH_Y, PODIUM_H + 2.3, COL_H - 5.2, COL_R, c["stone"],
                      flutes=24, groove=0.06, taper=0.90)
        # 柱头
        cyl(coll, f"柱头{i}", COL_R * 0.92, 2.0, (x, PORCH_Y, PODIUM_H + COL_H - 2.1),
            c["stone2"], 48, r2=COL_R * 1.42)
        box(coll, f"柱头板{i}", (4.4, 4.4, 0.8), (x, PORCH_Y, PODIUM_H + COL_H - 0.6), c["trim"])

    # ---------- 柱廊后墙 + 大门 ----------
    box(coll, "门廊后墙", (COL_SPAN + 10, 1.0, COL_H), (0, FRONT_Y - 0.4, PODIUM_H + COL_H / 2), c["glass"])
    for k in range(15):
        x = -COL_SPAN / 2 - 5 + COL_SPAN * k / 14
        box(coll, f"幕墙竖框{k}", (0.7, 1.4, COL_H), (x, FRONT_Y - 0.9, PODIUM_H + COL_H / 2), c["bronze2"])
    box(coll, "幕墙横框", (COL_SPAN + 10, 1.4, 0.7), (0, FRONT_Y - 0.9, PODIUM_H + COL_H - 4), c["bronze2"])
    for i, x in enumerate((-34, 0, 34)):
        box(coll, f"门洞{i}", (24, 1.5, 17), (x, FRONT_Y - 1.2, PODIUM_H + 9), c["glass"])
        box(coll, f"门框上{i}", (26, 2.0, 1.0), (x, FRONT_Y - 1.3, PODIUM_H + 17.8), c["bronze2"])
        for sx in (-1, 1):
            box(coll, f"门框侧{i}{sx}", (1.0, 2.0, 18), (x + sx * 12.4, FRONT_Y - 1.3, PODIUM_H + 9),
                c["bronze2"])
        for sx in (-1, 1):
            box(coll, f"门扇{i}{sx}", (11.6, 1.0, 16), (x + sx * 6.1, FRONT_Y - 1.9, PODIUM_H + 8.6), c["bronze"])
            for k in range(4):
                box(coll, f"门格{i}{sx}{k}", (9.2, 0.3, 2.8),
                    (x + sx * 6.1, FRONT_Y - 2.3, PODIUM_H + 2.8 + k * 3.6), c["bronze2"])

    # ---------- 额枋 / 檐口 ----------
    box(coll, "额枋1", (COL_SPAN + 18, 22, 2.2), (0, PORCH_Y, PODIUM_H + COL_H + 0.7), c["stone"])
    box(coll, "额枋2", (COL_SPAN + 24, 24, 1.6), (0, PORCH_Y, PODIUM_H + COL_H + 2.6), c["trim"])
    box(coll, "檐口", (COL_SPAN + 30, 27, 1.4), (0, PORCH_Y, PODIUM_H + COL_H + 4.1), c["trim"])
    box(coll, "柱廊顶板", (COL_SPAN + 16, 24, 1.0), (0, PORCH_Y + 1, PODIUM_H + COL_H + 5.3), c["roofm"])

    # ---------- 主体 ----------
    box(coll, "主体", (L, D, BODY_H), (0, 0, PODIUM_H + BODY_H / 2), c["stone"])
    box(coll, "主体线脚", (L + 3, D + 3, 1.0), (0, 0, ROOF_Z - 0.5), c["trim"])
    # 主体上方再收一层（真实建筑有退台感）
    box(coll, "主体上层", (L - 40, D - 34, 3.0), (0, 6, ROOF_Z + 1.5), c["stone2"])

    # ---------- 正立面两翼竖向窗 ----------
    for sx in (-1, 1):
        for k in range(6):
            x = sx * (98 + k * 12.0)
            box(coll, f"正窗框{sx}{k}", (7.4, 1.0, 21), (x, FRONT_Y + 0.2, PODIUM_H + 13), c["trim"])
            box(coll, f"正窗{sx}{k}", (6.2, 0.8, 19.6), (x, FRONT_Y - 0.1, PODIUM_H + 13), c["glass"])
        for k in range(5):
            x = sx * (92 + k * 15.0 + 7.0)
            box(coll, f"正壁柱{sx}{k}", (2.2, 3.0, 26), (x, FRONT_Y - 0.7, PODIUM_H + 13), c["stone2"])

    # ---------- 东西侧立面窗 ----------
    for sx in (-1, 1):
        for k in range(11):
            y = -78 + k * 15.6
            box(coll, f"侧窗框{sx}{k}", (1.0, 9.0, 18), (sx * (L / 2 - 0.1), y, PODIUM_H + 13), c["trim"])
            box(coll, f"侧窗{sx}{k}", (0.8, 7.8, 16.6), (sx * (L / 2 + 0.2), y, PODIUM_H + 13), c["glass"])
        for k in range(10):
            y = -70 + k * 15.6
            box(coll, f"侧壁柱{sx}{k}", (2.4, 3.0, 26), (sx * (L / 2 + 1.0), y, PODIUM_H + 13), c["stone2"])

    # ---------- 屋顶 ----------
    par = 3.0
    box(coll, "女儿墙前", (L, 2.2, par), (0, -D / 2 + 1.1, ROOF_Z + par / 2), c["stone"])
    box(coll, "女儿墙后", (L, 2.2, par), (0, D / 2 - 1.1, ROOF_Z + par / 2), c["stone"])
    box(coll, "女儿墙左", (2.2, D - 4.4, par), (-L / 2 + 1.1, 0, ROOF_Z + par / 2), c["stone"])
    box(coll, "女儿墙右", (2.2, D - 4.4, par), (L / 2 - 1.1, 0, ROOF_Z + par / 2), c["stone"])
    box(coll, "压顶前", (L + 1, 3.0, 0.4), (0, -D / 2 + 1.1, ROOF_Z + par + 0.2), c["trim"])
    box(coll, "压顶后", (L + 1, 3.0, 0.4), (0, D / 2 - 1.1, ROOF_Z + par + 0.2), c["trim"])

    # 中央塔楼
    box(coll, "中央塔楼", (86, 44, 6.5), (0, 10, ROOF_Z + 4.5), c["stone2"])
    box(coll, "塔楼檐口", (88, 46, 0.7), (0, 10, ROOF_Z + 7.8), c["trim"])
    # 塔楼两侧旗杆
    for sx in (-1, 1):
        cyl(coll, f"侧旗杆{sx}", 0.25, 14, (sx * 60, 10, ROOF_Z + 12), c["bronze"], 16)

    # ---------- 主旗杆 + 红旗 ----------
    pole_base = ROOF_Z + 10
    cyl(coll, "旗杆", 0.4, 32, (0, 10, pole_base + 16), c["bronze"], 24)
    cyl(coll, "旗杆顶", 0.7, 1.0, (0, 10, pole_base + 32.2), c["bronze2"], 24)
    box(coll, "旗", (13, 0.15, 8.2), (6.8, 10, pole_base + 27), c["red"])

    # ---------- 合并 ----------
    bpy.ops.object.select_all(action="DESELECT")
    for ob in PARTS:
        if ob.name in bpy.data.objects:
            ob.select_set(True)
    if PARTS:
        bpy.context.view_layer.objects.active = PARTS[0]
        bpy.ops.object.join()
        joined = bpy.context.active_object
        joined.name = "人民大会堂"
        try:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(26))
        except Exception:
            pass
    PARTS.clear()

    # ---------- 相机 / 灯光 ----------
    cam = bpy.data.objects.get("Camera")
    if cam:
        cam.location = (470, -720, 300)
        d = Vector((0, 0, 26)) - cam.location
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = 60
    sun = bpy.data.objects.get("Sun")
    if sun:
        sun.data.energy = 3.0
    bpy.context.view_layer.update()
    print("V3 DONE dims:", tuple(round(v, 1) for v in bpy.data.objects["人民大会堂"].dimensions))
    return bpy.data.objects.get("人民大会堂")


if __name__ == "__main__":
    build_v3()
