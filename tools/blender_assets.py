# Blender 无头模式: 生成孪生场景的设备精模 GLB
# 用法: Blender.app/Contents/MacOS/Blender -b --python tools/blender_assets.py
# 设计原则: 每个装配体 = 一个命名对象(细节件 join 进去, 多材质槽保留),
#           three.js 端按叶级命名节点拆解; 大表面必须有面板缝/螺栓/格栅等细节。
import bpy
import math
import os
from mathutils import Vector, Quaternion, Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "frontend", "public", "twin-assets")
os.makedirs(OUT, exist_ok=True)

# ---------- 基础工具 ----------

def clean():
    bpy.ops.wm.read_factory_settings(use_empty=True)

def mat(name, color, metallic=0.3, roughness=0.5, emission=None, estr=0.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    m.diffuse_color = (*color, 1)
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1)
        bsdf.inputs["Emission Strength"].default_value = estr
    return m

# 工业质感调色板
PAINT_WHITE = lambda: mat("paint_white", (0.72, 0.75, 0.79), 0.12, 0.38)   # 机身烤漆
PAINT_GRAY  = lambda: mat("paint_gray", (0.34, 0.37, 0.41), 0.25, 0.45)     # 结构灰
PAINT_DARK  = lambda: mat("paint_dark", (0.075, 0.085, 0.105), 0.35, 0.5)   # 深色饰板
PAINT_YELLOW= lambda: mat("paint_yellow", (0.85, 0.62, 0.06), 0.15, 0.48)   # 工程黄
PAINT_BLUE  = lambda: mat("paint_blue", (0.10, 0.22, 0.38), 0.25, 0.42)     # 港口蓝
IND_BLUE  = lambda: mat("ind_blue", (0.07, 0.20, 0.42), 0.3, 0.44)      # 堆垛机工业蓝
CONT_BLUE = lambda: mat("cont_blue", (0.10, 0.28, 0.55), 0.35, 0.5)     # 集装箱蓝
IND_GREEN = lambda: mat("ind_green", (0.16, 0.55, 0.35), 0.2, 0.5)      # Q-Truck 绿饰条
NAVY      = lambda: mat("navy", (0.07, 0.10, 0.16), 0.35, 0.5)          # 机房深蓝灰
METAL       = lambda: mat("metal", (0.46, 0.49, 0.53), 0.85, 0.30)          # 机加工面
METAL_DARK  = lambda: mat("metal_dark", (0.15, 0.16, 0.18), 0.75, 0.38)     # 深色金属
RUBBER      = lambda: mat("rubber", (0.045, 0.045, 0.05), 0.0, 0.92)        # 橡胶
GLASS       = lambda: mat("glass", (0.07, 0.12, 0.18), 0.9, 0.08)           # 玻璃
CYAN        = lambda: mat("cyan_glow", (0.04, 0.30, 0.34), 0.2, 0.4, (0.13, 0.84, 0.93), 1.9)
AMBER       = lambda: mat("amber_glow", (0.40, 0.26, 0.05), 0.2, 0.45, (0.96, 0.62, 0.04), 2.0)
REDG        = lambda: mat("red_glow", (0.40, 0.05, 0.04), 0.2, 0.45, (1.0, 0.14, 0.10), 1.8)

def _finish(o, name, material, bevel, smooth=False):
    o.name = name
    if bevel:
        mod = o.modifiers.new("bevel", "BEVEL")
        mod.width = bevel
        mod.segments = 3
        mod.harden_normals = True
        bpy.ops.object.modifier_apply(modifier="bevel")
    if smooth:
        # 曲面平滑着色 + 加权法线(否则圆柱/圆锥满身棱面, 一眼玩具)
        for poly in o.data.polygons:
            poly.use_smooth = True
        wn = o.modifiers.new("wn", "WEIGHTED_NORMAL")
        wn.keep_sharp = True
        bpy.ops.object.modifier_apply(modifier="wn")
    if material:
        o.data.materials.append(material)
    return o

def box(name, loc, scale, material, bevel=0.06, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.scale = (scale[0] / 2, scale[1] / 2, scale[2] / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return _finish(o, name, material, bevel)

def cyl(name, loc, radius, depth, material, bevel=0.03, rot=(0, 0, 0), verts=40):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=radius, depth=depth, location=loc, rotation=rot)
    return _finish(bpy.context.object, name, material, bevel, smooth=True)

def cone(name, loc, r1, r2, depth, material, bevel=0.03, rot=(0, 0, 0), verts=40):
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r1, radius2=r2, depth=depth, location=loc, rotation=rot)
    return _finish(bpy.context.object, name, material, bevel, smooth=True)

def sphere(name, loc, radius, material, seg=20):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=12, radius=radius, location=loc)
    return _finish(bpy.context.object, name, material, 0, smooth=True)

RED = lambda: mat("paint_red", (0.62, 0.12, 0.10), 0.2, 0.5)       # 哑光大红漆(叶尖警示)

def torus(name, loc, major, minor, material, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor,
                                     major_segments=36, minor_segments=10, location=loc, rotation=rot)
    return _finish(bpy.context.object, name, material, 0, smooth=True)

def rod_between(name, p1, p2, radius, material, bevel=0.01):
    """两点之间的圆杆(拉杆/栏杆/线缆)。"""
    p1, p2 = Vector(p1), Vector(p2)
    d = p2 - p1
    mid = (p1 + p2) / 2
    o = cyl(name, mid, radius, d.length, material, bevel)
    o.rotation_mode = "QUATERNION"
    o.rotation_quaternion = d.to_track_quat("Z", "Y")
    o.rotation_mode = "XYZ"
    return o

def pipe(name, points, radius, material):
    """贝塞尔圆管(线缆/液压管), 转网格保证导出。"""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 2
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(points) - 1)
    for bp, co in zip(sp.bezier_points, points):
        bp.co = co
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    o = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(o)
    if material:
        cu.materials.append(material)
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.convert(target="MESH")
    return o

def bolt_ring(loc, radius, count, bolt_r, bolt_h, material, axis="Z"):
    """一圈螺栓, 返回对象列表(调用方 join)。"""
    objs = []
    rot = (0, 0, 0) if axis == "Z" else (math.pi / 2, 0, 0)
    for i in range(count):
        a = i / count * 2 * math.pi
        if axis == "Z":
            p = (loc[0] + math.cos(a) * radius, loc[1] + math.sin(a) * radius, loc[2])
        else:
            p = (loc[0] + math.cos(a) * radius, loc[1], loc[2] + math.sin(a) * radius)
        objs.append(cyl(f"_bolt{i}", p, bolt_r, bolt_h, material, 0.008, rot=rot, verts=12))
    return objs

def hazard_stripes(loc, length, width, axis="X", step=0.5, h=0.025):
    """黄黑警示条纹, 返回对象列表。"""
    objs = []
    n = max(2, int(length / step))
    for i in range(n):
        m = PAINT_YELLOW() if i % 2 == 0 else PAINT_DARK()
        off = -length / 2 + (i + 0.5) * (length / n)
        p = list(loc)
        p[0 if axis == "X" else 1] += off
        s = [width, h, width]
        s[0 if axis == "X" else 1] = length / n
        objs.append(box(f"_hz{i}", p, s, m, 0.005, rot=(0, 0, math.radians(0))))
    return objs

def railing(x0, y0, x1, y1, z, height=1.0, posts=6, material=None):
    """两段式扶手栏杆, 返回对象列表。"""
    material = material or METAL()
    objs = []
    for i in range(posts):
        t = i / (posts - 1)
        x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
        objs.append(cyl(f"_rp{i}", (x, y, z + height / 2), 0.03, height, material, 0.005, verts=10))
    for zz in (z + height, z + height * 0.55):
        objs.append(rod_between(f"_rr{zz}", (x0, y0, zz), (x1, y1, zz), 0.025, material, 0.004))
    return objs

def ladder(x, y, z0, z1, width=0.45, material=None):
    """直爬梯(竖板 + 踏步), 返回对象列表。"""
    material = material or METAL()
    objs = []
    h = z1 - z0
    for yy in (y - width / 2, y + width / 2):
        objs.append(box("_lr", (x, yy, z0 + h / 2), (0.06, 0.05, h), material, 0.01))
    n = int(h / 0.32)
    for i in range(n):
        zz = z0 + 0.2 + i * (h - 0.4) / max(1, n - 1)
        objs.append(cyl(f"_lg{i}", (x, y, zz), 0.018, width, material, 0.003, rot=(math.pi / 2, 0, 0), verts=8))
    return objs

def stair_flight(p1, p2, width=0.85, material=None):
    """斜梯单跑(沿 X 或 Y 爬升): 踏步板 + 双弦杆 + 两侧扶手, 返回对象列表。"""
    material = material or METAL()
    objs = []
    dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
    along_x = abs(dx) >= abs(dy)
    run = math.hypot(dx, dy)
    length = math.hypot(run, dz)
    ang = math.atan2(dz, run)
    n = max(3, int(abs(dz) / 0.26))
    for i in range(n):   # 踏步(水平小板)
        t = (i + 0.5) / n
        sc = (0.27, width, 0.05) if along_x else (width, 0.27, 0.05)
        objs.append(box(f"_st{i}", (p1[0] + dx * t, p1[1] + dy * t, p1[2] + dz * t), sc, material, 0.008))
    # 双弦杆(坡面长梁): 沿坡向倾转
    mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, (p1[2] + p2[2]) / 2 - 0.10)
    if along_x:
        for yoff in (-width / 2, width / 2):
            objs.append(box("_str", (mid[0], mid[1] + yoff, mid[2]), (length, 0.06, 0.24), material, 0.01, rot=(0, -ang if dx > 0 else ang, 0)))
    else:
        for xoff in (-width / 2, width / 2):
            objs.append(box("_str", (mid[0] + xoff, mid[1], mid[2]), (0.06, length, 0.24), material, 0.01, rot=(ang if dy > 0 else -ang, 0, 0)))
    # 两侧扶手(高/中双杆 + 端部立柱)
    for s in (-1, 1):
        o = (0, s * (width / 2 + 0.02)) if along_x else (s * (width / 2 + 0.02), 0)
        for hh in (0.92, 0.5):
            objs.append(rod_between("_hr", (p1[0] + o[0], p1[1] + o[1], p1[2] + hh), (p2[0] + o[0], p2[1] + o[1], p2[2] + hh), 0.024, material, 0.004))
        for t in (0.06, 0.94):
            objs.append(cyl("_hp", (p1[0] + dx * t + o[0], p1[1] + dy * t + o[1], p1[2] + dz * t + 0.46), 0.024, 0.92, material, 0.004, verts=8))
    return objs

def vent_slats(loc, w, h, n=5, gap=None, material=None, rot=(0, 0, 0)):
    """散热格栅: 底板 + 百叶条, 返回对象列表。"""
    material = material or PAINT_DARK()
    gap = gap or h / (n * 1.6)
    objs = [box("_vbase", loc, (w, 0.03, h), material, 0.01, rot=rot)]
    for i in range(n):
        zz = loc[2] - h / 2 + (i + 0.5) * (h / n)
        objs.append(box(f"_vs{i}", (loc[0], loc[1] - 0.02, zz), (w * 0.9, 0.03, h / n - gap), METAL_DARK(), 0.004, rot=rot))
    return objs

def wheel(name, loc, r, width, axis="X"):
    """轮胎+轮毂+螺栓, 直接 join 成一个命名对象。"""
    rot = (0, math.pi / 2, 0) if axis == "X" else (math.pi / 2, 0, 0)
    tire = cyl(name, loc, r, width, RUBBER(), 0.05, rot=rot, verts=36)
    rim_r = r * 0.52
    parts = [cyl("_rim", loc, rim_r, width + 0.04, METAL(), 0.02, rot=rot, verts=24)]
    # 轮毂端面螺栓(外侧)
    off = width / 2 + 0.03
    for i in range(6):
        a = i / 6 * 2 * math.pi
        if axis == "X":
            p = (loc[0] + off, loc[1] + math.cos(a) * rim_r * 0.55, loc[2] + math.sin(a) * rim_r * 0.55)
        else:
            p = (loc[0] + math.cos(a) * rim_r * 0.55, loc[1] + off, loc[2] + math.sin(a) * rim_r * 0.55)
        parts.append(cyl(f"_wb{i}", p, r * 0.05, 0.04, METAL_DARK(), 0.005, rot=rot, verts=10))
    return join_into(tire, parts)

def join_into(target, objs):
    """把细节件并入装配体(材质槽保留), 返回 target。"""
    bpy.ops.object.select_all(action="DESELECT")
    target.select_set(True)
    n = 1
    for o in objs:
        if o and o != target and o.name in bpy.data.objects:
            o.select_set(True)
            n += 1
    bpy.context.view_layer.objects.active = target
    if n > 1:
        bpy.ops.object.join()
    return target

def new_empty(name, loc):
    e = bpy.data.objects.new(name, None)
    e.location = loc
    bpy.context.scene.collection.objects.link(e)
    return e

def parent_keep_world(obj, parent):
    bpy.context.view_layer.update()   # 空对象用 data API 创建, 矩阵是脏的, 必须先刷新
    mw = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = mw

def export_glb(name):
    path = os.path.join(OUT, name + ".glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True)
    print("exported", path)

# ---------- 资产 9: 卡口监控单元(天眼交通入口装备: 立杆/悬臂/3 枪机/爆闪灯/控制箱) ----------

def build_traffic_pole():
    clean()
    # v2 细化: 镀锌八角锥杆 + 桁架悬臂 + 全结构枪机(遮光罩/镜筒/红外环/万向支架)
    # 调色: 热镀锌钢(结构件) + 烤漆白(设备腔体)
    GALV = lambda: mat("galv", (0.60, 0.63, 0.66), 0.62, 0.48)
    WHITE = PAINT_WHITE(); GRAY = PAINT_GRAY(); DARK = PAINT_DARK(); MET = METAL(); METD = METAL_DARK()
    # 法兰底座: 基板 + 四加劲板 + 八锚栓
    flange = box("flange", (0, 0, 0.04), (0.72, 0.72, 0.08), METD, 0.02)
    gus = []
    for i in range(4):
        a = math.radians(45 + i * 90)
        gus.append(box(f"_gs{i}", (math.cos(a) * 0.2, math.sin(a) * 0.2, 0.24), (0.05, 0.16, 0.34), METD, 0.01, rot=(0, 0, a + math.pi / 2)))
    join_into(flange, gus + bolt_ring((0, 0, 0.11), 0.29, 8, 0.022, 0.07, MET))
    # 立杆: 八角锥形镀锌杆(verts=8 八角截面, 0.06..6.56m) + 顶帽 + 检修门 + 黄黑警示环 + 背部走线槽
    pole = cone("pole", (0, 0, 3.31), 0.15, 0.10, 6.5, GALV(), 0.012, verts=8)
    cap = sphere("_pcap", (0, 0, 6.58), 0.105, GALV())
    door = [box("_door", (0, -0.145, 1.25), (0.18, 0.025, 0.54), GRAY, 0.008),
            # 门框(四条细边) + 铰链 + 把手
            box("_df_t", (0, -0.150, 1.52), (0.19, 0.012, 0.018), METD, 0.003),
            box("_df_b", (0, -0.150, 0.98), (0.19, 0.012, 0.018), METD, 0.003),
            box("_df_l", (-0.088, -0.150, 1.25), (0.018, 0.012, 0.54), METD, 0.003),
            box("_df_r", (0.088, -0.150, 1.25), (0.018, 0.012, 0.54), METD, 0.003),
            cyl("_hinge1", (0.095, -0.148, 1.10), 0.008, 0.05, METD, 0.002, verts=10),
            cyl("_hinge2", (0.095, -0.148, 1.40), 0.008, 0.05, METD, 0.002, verts=10),
            box("_lock", (-0.06, -0.158, 1.25), (0.03, 0.02, 0.09), METD, 0.005)]
    # 黄黑警示环(杆底 0.55..0.85m 两段)
    warn = [cyl("_warn_y", (0, 0, 0.62), 0.152, 0.24, PAINT_YELLOW(), 0.004, verts=8),
            cyl("_warn_d1", (0, 0, 0.52), 0.154, 0.055, PAINT_DARK(), 0.002, verts=8),
            cyl("_warn_d2", (0, 0, 0.72), 0.150, 0.055, PAINT_DARK(), 0.002, verts=8)]
    conduit = [box("_conduit", (0, 0.128, 3.2), (0.045, 0.028, 4.4), DARK, 0.006)]
    join_into(pole, [cap] + door + warn + conduit)
    # 检修控制箱: 壳体 + 雨檐 + 门框 + 散热格栅 + 门锁 + 底部线缆格兰 + 警示标牌
    cabinet = box("cabinet", (0.38, 0, 1.35), (0.36, 0.5, 0.8), GRAY, 0.02)
    join_into(cabinet, vent_slats((0.38, -0.26, 1.5), 0.26, 0.3, 4) +
                     [box("_hood", (0.38, -0.02, 1.79), (0.42, 0.56, 0.05), GRAY, 0.012),
                      box("_df2_t", (0.38, -0.262, 1.62), (0.30, 0.014, 0.02), METD, 0.003),
                      box("_df2_b", (0.38, -0.262, 1.08), (0.30, 0.014, 0.02), METD, 0.003),
                      box("_df2_l", (0.245, -0.262, 1.35), (0.02, 0.014, 0.56), METD, 0.003),
                      box("_df2_r", (0.515, -0.262, 1.35), (0.02, 0.014, 0.56), METD, 0.003),
                      box("_handle", (0.30, -0.285, 1.35), (0.025, 0.03, 0.14), METD, 0.006),
                      cyl("_gland", (0.38, 0, 0.93), 0.028, 0.05, METD, 0.004, verts=12),
                      box("_plate", (0.38, -0.268, 1.05), (0.14, 0.012, 0.09), PAINT_YELLOW(), 0.004)])
    # 悬臂桁架: 上弦 + 下弦 + 立杆/斜腹杆(交替) + 端封板 + 根部加强
    arm = box("arm", (2.45, 0, 6.97), (4.3, 0.10, 0.10), GALV(), 0.012)   # 上弦
    truss = [box("_chord_lo", (2.45, 0, 6.70), (4.3, 0.08, 0.08), GALV(), 0.01)]   # 下弦
    for i in range(11):
        x = 0.35 + i * 0.42
        truss.append(box(f"_web_v{i}", (x, 0, 6.835), (0.035, 0.05, 0.28), GALV(), 0.005))   # 立杆
        if i < 10:
            truss.append(rod_between(f"_web_d{i}", (x, 0, 6.72), (x + 0.42, 0, 6.96), 0.022, GALV()))   # 斜腹杆
    truss.append(box("_endcap", (4.62, 0, 6.84), (0.06, 0.14, 0.30), GALV(), 0.008))
    truss.append(rod_between("_root_gus", (0, 0, 5.7), (1.3, 0, 6.70), 0.05, GALV()))   # 根部斜撑
    truss.append(box("_cap", (0, 0, 6.62), (0.3, 0.3, 0.08), GALV(), 0.015))
    join_into(arm, truss)
    # 枪机相机(后腔 + 机身 + 遮光罩带唇边 +  bezel 环 + 玻璃镜片 + 红外点阵 + 吊板 + 转接盘 + 球头 + 线缆尾)
    def bullet_cam(name, x, pivot_origin=False):
        zA = 6.55   # 机身中心高(臂下)
        body = cyl(name, (x, 0, zA), 0.085, 0.34, WHITE, 0.012, rot=(0, math.pi / 2, 0))
        parts = [
            box("_rear", (x - 0.16, 0, zA + 0.01), (0.14, 0.11, 0.11), WHITE, 0.012),                    # 后腔
            cyl("_hood", (x + 0.15, 0, zA), 0.105, 0.20, WHITE, 0.012, rot=(0, math.pi / 2, 0)),         # 遮光罩
            box("_hood_lip", (x + 0.24, 0, zA + 0.09), (0.20, 0.115, 0.018), WHITE, 0.004),              # 罩唇(防雨)
            cyl("_bezel", (x + 0.20, 0, zA), 0.062, 0.025, DARK, 0.004, rot=(0, math.pi / 2, 0)),        # bezel 环
            cyl("_lens", (x + 0.21, 0, zA), 0.048, 0.04, GLASS(), 0.004, rot=(0, math.pi / 2, 0)),       # 玻璃镜片
            box("_drop", (x - 0.05, 0, 6.70), (0.06, 0.04, 0.12), GALV(), 0.006),                        # 吊板(臂下)
            cyl("_swivel", (x - 0.05, 0, 6.665), 0.055, 0.028, METD, 0.004),                             # 转接盘
            sphere("_knuckle", (x - 0.05, 0, 6.62), 0.05, METD),                                         # 球头
            cyl("_gland", (x - 0.22, 0, zA + 0.02), 0.02, 0.05, METD, 0.003, rot=(0, math.pi / 2, 0), verts=10),  # 尾部格兰
            pipe("_cbl", [(x - 0.24, 0, zA + 0.02), (x - 0.3, 0, 6.68), (x - 0.34, 0, 6.76)], 0.011, DARK),  # 线缆尾上臂
        ]
        # 红外补光点阵(镜片周围 6 颗, 暗红微光)
        for i in range(6):
            a = i / 6 * 2 * math.pi
            parts.append(cyl(f"_ir{i}", (x + 0.215, math.cos(a) * 0.072, zA + math.sin(a) * 0.072), 0.006, 0.012, REDG(), 0.001, rot=(0, math.pi / 2, 0), verts=8))
        joined = join_into(body, parts)
        if pivot_origin:
            # cam_b 原点钉在球头中心(云台枢轴): 默认几何中心原点会让扫视变成甩摆
            bpy.context.scene.cursor.location = (x - 0.05, 0, 6.62)
            bpy.ops.object.select_all(action="DESELECT")
            joined.select_set(True)
            bpy.context.view_layer.objects.active = joined
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
        return joined
    bullet_cam("cam_a", 1.1)
    bullet_cam("cam_b", 2.4, pivot_origin=True)
    bullet_cam("cam_c", 3.7)
    # 爆闪补光灯: 后腔散热齿 + 灯箱 + 前唇 + LED 面板(独立命名, 动画驱动爆闪)
    strobe = box("strobe", (3.0, 0, 6.55), (0.40, 0.13, 0.30), DARK, 0.015)
    join_into(strobe, [box("_visor", (3.22, 0, 6.60), (0.04, 0.15, 0.32), METD, 0.005),
                       box("_hood2", (3.05, 0, 6.73), (0.34, 0.15, 0.03), DARK, 0.006)] +
                     [box(f"_fin{i}", (2.82 - i * 0.035, 0.075, 6.55), (0.02, 0.02, 0.24), METD, 0.002) for i in range(4)])
    ledm = mat("strobe_led_mat", (0.9, 0.92, 0.85), 0.1, 0.4, (1.0, 0.98, 0.9), 0.6)
    box("strobe_led", (3.245, 0, 6.55), (0.02, 0.10, 0.24), ledm, 0.003)
    export_glb("traffic_pole")

# ---------- 资产 1: KUKA LBR iiwa 14 机械臂(真机 CAD, MJCF 运动链装配) ----------

def build_robot_cell():
    clean()
    # KUKA LBR iiwa 14 真机 CAD(MuJoCo Menagerie 收录, 网格源自 Drake, BSD-3-Clause)
    # 严格按 iiwa14.xml 装配: 关节空轴串成运动链 + 连杆网格挂对应空轴, 零位=官方 home
    SRC = os.path.join(ROOT, "tools", "iiwa14")
    # 涂装对齐真机 LBR iiwa 14 R820: 银白铝机身 + KUKA 橙关节带 + 深色铭牌带
    # (MJCF 默认 0.4 灰是 Drake 演示色, 真机是浅色铝——深灰显闷显玩具)
    GRAY = mat("kuka_gray", (0.74, 0.75, 0.77), 0.18, 0.38)
    LIGHT = mat("kuka_light", (0.88, 0.89, 0.90), 0.15, 0.42)
    BLACK = mat("kuka_black", (0.028, 0.03, 0.032), 0.3, 0.46)
    ORANGE = mat("kuka_orange", (1.0, 0.4235, 0.0392), 0.22, 0.4)

    def load_mesh(fname, material):
        before = set(bpy.data.objects)
        bpy.ops.wm.obj_import(filepath=os.path.join(SRC, fname + ".obj"),
                              forward_axis="Y", up_axis="Z")   # 原始米制 z-up 坐标, 不做轴转换
        news = [o for o in bpy.data.objects if o not in before]
        for o in news[1:]:
            bpy.data.objects.remove(o, do_unlink=True)
        ob = news[0]
        ob.data.materials.clear()
        ob.data.materials.append(material)
        for p in ob.data.polygons:
            p.use_smooth = True
        return ob

    # (关节, 父关节, pos, quat(w,x,y,z), [(网格, 材质)...]) —— 逐项引自 iiwa14.xml
    chain = [
        ("j1", None, (0, 0, 0.1575), (1, 0, 0, 0), [("link_1", GRAY)]),
        ("j2", "j1", (0, 0, 0.2025), (0, 0, 1, 1), [("link_2_orange", ORANGE), ("link_2_grey", GRAY)]),
        ("j3", "j2", (0, 0.2045, 0), (0, 0, 1, 1), [("link_3", GRAY), ("band", LIGHT), ("kuka", BLACK)]),
        ("j4", "j3", (0, 0, 0.2155), (1, 1, 0, 0), [("link_4_orange", ORANGE), ("link_4_grey", GRAY)]),
        ("j5", "j4", (0, 0.1845, 0), (0, 0, 1, 1), [("link_5", GRAY), ("band", LIGHT), ("kuka", BLACK)]),
        ("j6", "j5", (0, 0, 0.2155), (1, 1, 0, 0), [("link_6_orange", ORANGE), ("link_6_grey", GRAY)]),
        ("j7", "j6", (0, 0.081, 0), (0, 0, 1, 1), [("link_7", GRAY)]),
    ]
    HOME = {"j2": 0.785398, "j4": -1.5708}   # 官方 keyframe home: 展台姿态自然弯曲
    base = load_mesh("link_0", GRAY)
    base.name = "link_base"
    empties = {}
    for name, parent, pos, quat, meshes in chain:
        e = new_empty(name, pos)
        e.rotation_mode = "QUATERNION"
        q = Quaternion(quat)
        if name in HOME:
            a = HOME[name]
            q = q @ Quaternion((math.cos(a / 2), 0, 0, math.sin(a / 2)))   # MJCF 铰链轴=体轴 z
        e.rotation_quaternion = q
        if parent:
            e.parent = empties[parent]      # pos/quat 本就是 MJCF 父系局部坐标, 直接挂上即可
            e.matrix_parent_inverse = Matrix.Identity(4)
        empties[name] = e
        parts = [load_mesh(f, m) for f, m in meshes]
        link = parts[0]
        link.name = "link" + name[1:]
        if len(parts) > 1:
            join_into(link, parts[1:])
        link.parent = e
        link.matrix_parent_inverse = Matrix.Identity(4)
        link.location = (0, 0, 0)
    # 末端挂点(MJCF attachment_site): 忠实还原结构, 也让 j7 保持纯关节(不当部件)
    site = new_empty("attachment_site", (0, 0, 0.045))
    site.parent = empties["j7"]
    site.matrix_parent_inverse = Matrix.Identity(4)
    # 末端 ISO 9409 法兰 + 安装螺栓(真机腕部必有件, 没有就是"秃腕")
    flange = cyl("end_tool", (0, 0, 0.052), 0.045, 0.016, METAL_DARK(), 0.004, verts=40)
    join_into(flange, bolt_ring((0, 0, 0.062), 0.032, 4, 0.004, 0.006, METAL()))
    flange.parent = empties["j7"]
    flange.matrix_parent_inverse = Matrix.Identity(4)
    # 安装台座(顶面与基座法兰齐平) + 锚栓 + 示廓灯环
    ped = cyl("pedestal", (0, 0, -0.035), 0.19, 0.07, METAL_DARK(), 0.012, verts=48)
    join_into(ped, bolt_ring((0, 0, 0.004), 0.14, 6, 0.012, 0.012, METAL())
              + [torus("_pring", (0, 0, -0.001), 0.165, 0.008, CYAN())])
    # 整体落地: 根空轴抬一个台座厚度, 场景 zmin=0
    root = new_empty("iiwa_root", (0, 0, 0.07))
    for o in (base, ped, empties["j1"]):
        o.parent = root
        o.matrix_parent_inverse = Matrix.Identity(4)
    export_glb("robot_cell")

# ---------- 资产 2: 岸桥(STS) ----------

def build_sts_crane():
    clean()
    H = 18.0
    # 门腿(带台车/锚定板/爬梯)
    for x in (-5.2, 5.2):
        for z in (-3.4, 3.4):
            leg = box(f"leg_{x}_{z}", (x, z, H / 2 + 1.2), (0.9, 0.9, H), PAINT_WHITE(), 0.05)
            details = [
                box("_anchor", (x, z, 1.45), (1.5, 1.5, 0.22), PAINT_GRAY(), 0.04),
                box("_bogie", (x, z, 0.72), (1.9, 1.4, 0.85), PAINT_BLUE(), 0.08),
                box("_bcap1", (x, z - 0.72, 0.72), (1.5, 0.06, 0.5), PAINT_YELLOW(), 0.01),
                box("_bcap2", (x, z + 0.72, 0.72), (1.5, 0.06, 0.5), PAINT_YELLOW(), 0.01),
                cyl("_bw1", (x - 0.55, z - 0.58, 0.34), 0.32, 0.2, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0)),
                cyl("_bw2", (x + 0.55, z - 0.58, 0.34), 0.32, 0.2, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0)),
                cyl("_bw3", (x - 0.55, z + 0.58, 0.34), 0.32, 0.2, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0)),
                cyl("_bw4", (x + 0.55, z + 0.58, 0.34), 0.32, 0.2, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0)),
            ]
            details += bolt_ring((x, z, 1.58), 0.6, 6, 0.04, 0.06, METAL_DARK())
            # v2: 腿基检修门(门框+门板) + 门楣踏步 + 柱顶节点角撑
            sx = 0.48 if x < 0 else -0.48
            details.append(box("_ldoorf", (x + sx * 1.04, z, 2.62), (0.04, 0.8, 1.3), METAL_DARK(), 0.008))
            details.append(box("_ldoor", (x + sx * 1.1, z, 2.62), (0.05, 0.64, 1.14), PAINT_DARK(), 0.01))
            details.append(box("_lstep", (x + sx * 1.35, z, 1.98), (0.42, 0.6, 0.09), METAL(), 0.01))
            details.append(rod_between("_knee", (x, z, H - 1.6), (x * 0.76, z, H + 0.72), 0.12, PAINT_GRAY(), 0.02))
            if x > 0 and z < 0:   # 海侧右腿上爬梯
                details += ladder(x + 0.52, z, 1.6, H + 0.6)
            join_into(leg, details)
    # 顶部横梁(带警示纹)
    for z in (-3.4, 3.4):
        beam = box(f"beam_{z}", (0, z, H + 1.2), (11.9, 0.95, 1.15), PAINT_WHITE(), 0.06)
        join_into(beam, hazard_stripes((0, z - 0.49, H + 0.75), 11.4, 0.35))
    # X 型斜撑 + 节点板
    for z in (-3.4, 3.4):
        for x in (-5.2, 5.2):
            sign = 1 if x < 0 else -1
            xb = rod_between(f"xbrace{x}_{z}", (x, z, 1.8), (-x * 0.06, z, H + 0.9), 0.14, PAINT_GRAY(), 0.02)
            join_into(xb, [box("_gus", (x * 0.96, z, 2.0), (0.5, 0.3, 0.5), PAINT_GRAY(), 0.03)])
    # 底横梁
    for i, z in enumerate((-3.4, 3.4)):
        sill = box(f"sill{i+1}", (0, z, 1.05), (12.6, 1.25, 0.85), PAINT_BLUE(), 0.06)
        join_into(sill, hazard_stripes((0, z - 0.64 if z < 0 else z + 0.64, 1.05), 12.0, 0.4))
    # v2: 登机斜梯(陆侧腿间三折返: 踏步 + 弦杆 + 扶手 + 平台 + 平台栏杆) —— 独立部件
    SY = 4.02
    stairs = box("stairs", (0.95, SY, 7.28), (1.6, 1.15, 0.1), METAL(), 0.02)   # 转折平台 1 作主件
    st = [box("_plat2", (-5.05, SY, 12.58), (1.6, 1.15, 0.1), METAL(), 0.02),
          box("_plat3", (0.95, SY, 17.88), (2.1, 1.15, 0.1), METAL(), 0.02)]
    st += stair_flight((-4.55, SY, 1.9), (0.45, SY, 7.2))
    st += stair_flight((0.45, SY, 7.28), (-4.35, SY, 12.5))
    st += stair_flight((-4.35, SY, 12.58), (0.45, SY, 17.8))
    st += railing(0.15, SY + 0.56, 1.75, SY + 0.56, 7.38, 0.9, 3, PAINT_YELLOW())
    st += railing(-5.85, SY + 0.56, -4.25, SY + 0.56, 12.68, 0.9, 3, PAINT_YELLOW())
    st += railing(-0.15, SY + 0.56, 2.0, SY + 0.56, 17.98, 0.9, 3, PAINT_YELLOW())
    join_into(stairs, st)
    # v2: 电缆卷盘(陆侧右腿后方: 卷筒 + 橙色电缆 + 支架 + 驱动电机 + 下坑电缆) —— 独立部件
    reel = cyl("cable_reel", (5.2, 4.3, 2.85), 0.92, 0.78, mat("cable_orange", (0.75, 0.26, 0.07), 0.2, 0.55), 0.02, rot=(math.pi / 2, 0, 0))
    rd = [
        cyl("_rdisc1", (5.2, 3.88, 2.85), 1.16, 0.09, PAINT_YELLOW(), 0.02, rot=(math.pi / 2, 0, 0)),
        cyl("_rdisc2", (5.2, 4.72, 2.85), 1.16, 0.09, PAINT_YELLOW(), 0.02, rot=(math.pi / 2, 0, 0)),
        cyl("_rhub", (5.2, 4.3, 2.85), 0.16, 1.3, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0)),
        box("_rcheek1", (5.2, 3.82, 1.95), (0.85, 0.1, 1.55), PAINT_GRAY(), 0.03),
        box("_rcheek2", (5.2, 4.78, 1.95), (0.85, 0.1, 1.55), PAINT_GRAY(), 0.03),
        box("_rbase", (5.2, 4.3, 1.24), (1.15, 1.4, 0.14), PAINT_GRAY(), 0.03),
        box("_rmotor", (5.2, 3.62, 2.9), (0.55, 0.42, 0.5), PAINT_DARK(), 0.04),
        pipe("_rcable", [(5.2, 4.3, 1.95), (5.2, 4.5, 0.9), (5.2, 5.9, 0.35), (5.2, 7.6, 0.22)], 0.055, RUBBER()),
    ]
    join_into(reel, rd)
    # 大梁: 箱型主梁 + 加强肋 + 小车轨 + 顶部走道栏杆
    boom = box("boom", (0, -9, H + 2.1), (1.6, 36, 1.4), PAINT_WHITE(), 0.06)
    bd = []
    for i in range(8):
        yy = -25.5 + i * 4.7
        bd.append(box(f"_stiff{i}", (0, yy, H + 2.1), (1.72, 0.14, 1.5), PAINT_GRAY(), 0.02))
    for xx in (-0.85, 0.85):
        bd.append(box("_trail", (xx, -9, H + 1.32), (0.18, 35.5, 0.16), METAL(), 0.02))
    bd.append(box("_walk", (0, -9, H + 2.86), (0.9, 35.5, 0.07), METAL_DARK(), 0.01))
    bd += railing(-0.42, -26.5, -0.42, 8.5, H + 2.9, 0.9, 9, PAINT_YELLOW())
    bd += railing(0.42, -26.5, 0.42, 8.5, H + 2.9, 0.9, 9, PAINT_YELLOW())
    # v2: 底翼缘板 + 端部渐缩段 + 端部滑轮罩 + 端底警示板 + 端部障碍灯
    for xx in (-0.83, 0.83):
        bd.append(box("_flange", (xx, -9, H + 1.44), (0.08, 35.5, 0.2), PAINT_GRAY(), 0.015))
    bd.append(box("_tip", (0, -26.6, H + 1.95), (1.25, 2.4, 1.0), PAINT_WHITE(), 0.05))
    bd.append(cyl("_tipsheave", (0, -27.9, H + 1.95), 0.34, 1.0, METAL_DARK(), 0.02, rot=(0, math.pi / 2, 0)))
    bd.append(box("_tiphaz", (0, -26.6, H + 1.42), (1.0, 2.0, 0.06), PAINT_YELLOW(), 0.005))
    bd.append(sphere("_tipbeacon", (0, -26.6, H + 2.6), 0.11, REDG()))
    # v2: 拖令电缆系统(钢丝绳 + 挂环 + 拖令小车; 全部布在陆侧 y≥-7.4,
    # 小车行程 -10.4..-17.6 永不与拖令车重叠 —— 穿模防线)
    bd.append(rod_between("_festwire", (0.95, -8.2, H + 1.28), (0.95, 6.6, H + 1.28), 0.02, METAL_DARK(), 0.004))
    for i in range(7):
        fy = -7.4 + i * 2.25
        bd.append(box("_festcar", (0.95, fy, H + 1.33), (0.2, 0.34, 0.14), PAINT_DARK(), 0.02))
        bd.append(pipe("_festloop", [(0.95, fy - 0.62, H + 1.26), (0.95, fy, H + 0.5), (0.95, fy + 0.62, H + 1.26)], 0.038, RUBBER()))
    join_into(boom, bd)
    # A 字架(双腿 + 顶梁 + 航空障碍灯; 对标 ZPMC: A 架顶/轨距 ≈3.0, 提高 A 架占比)
    apex = (0, 4.4, H + 8.6)
    frame = box("frame_top", apex, (0.7, 3.2, 0.55), PAINT_WHITE(), 0.05)
    join_into(frame, [
        rod_between("_af1", (0, 2.4, H + 1.2), apex, 0.22, PAINT_WHITE(), 0.03),
        rod_between("_af2", (0, 6.4, H + 1.2), apex, 0.22, PAINT_WHITE(), 0.03),
        sphere("_beacon", (0, 4.4, H + 9.05), 0.16, REDG()),
        cyl("_apexshv", (0, 2.72, H + 8.45), 0.42, 0.5, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0)),   # v2: 架顶滑轮罩
        box("_apexplate", (0, 4.4, H + 8.28), (1.1, 1.6, 0.14), PAINT_GRAY(), 0.03),                   # v2: 架顶检修台
    ])
    # 拉杆(前拉大梁, 后拉机房)
    rod_between("tie_f", apex, (0, -25.5, H + 2.8), 0.09, METAL(), 0.015)
    rod_between("tie_b", apex, (0, 8.0, H + 2.95), 0.09, METAL(), 0.015)
    # 机房(带格栅/扶手/排气管/门)
    mach = box("machinery", (0, 6.0, H + 1.55), (6.4, 4.4, 2.7), NAVY(), 0.14)
    md = [
        cyl("_stack", (2.2, 5.2, H + 3.6), 0.22, 1.5, METAL_DARK(), 0.03),
        box("_door", (0, 2.98, H + 1.1), (1.0, 0.06, 1.9), PAINT_DARK(), 0.02),
        # v2: 屋面挑檐 + 检修天窗 + 第二排气管 + 屋面障碍灯 + 底部电缆喇叭口 + 海侧投光灯排 + 屋面直梯
        box("_roof", (0, 6.0, H + 2.94), (6.9, 4.9, 0.14), PAINT_WHITE(), 0.05),
        box("_hatch", (-1.6, 5.4, H + 3.12), (1.0, 1.0, 0.24), PAINT_GRAY(), 0.03),
        cyl("_stack2", (1.4, 6.9, H + 3.45), 0.15, 1.25, METAL_DARK(), 0.02),
        sphere("_mbeacon", (-2.9, 7.8, H + 3.3), 0.1, REDG()),
        cone("_horn1", (-1.2, 4.1, H + 0.16), 0.34, 0.2, 0.45, METAL_DARK(), 0.02, rot=(math.pi, 0, 0)),
        cone("_horn2", (1.2, 4.1, H + 0.16), 0.34, 0.2, 0.45, METAL_DARK(), 0.02, rot=(math.pi, 0, 0)),
        box("_fl1", (-1.5, 3.74, H + 0.32), (0.36, 0.2, 0.18), AMBER(), 0.02, rot=(math.radians(22), 0, 0)),
        box("_fl2", (0.0, 3.74, H + 0.32), (0.36, 0.2, 0.18), AMBER(), 0.02, rot=(math.radians(22), 0, 0)),
        box("_fl3", (1.5, 3.74, H + 0.32), (0.36, 0.2, 0.18), AMBER(), 0.02, rot=(math.radians(22), 0, 0)),
    ]
    md += ladder(-3.24, 6.0, H + 0.3, H + 2.9)
    md += vent_slats((-1.8, 2.97, H + 1.8), 1.6, 1.2, 5)
    md += vent_slats((1.2, 2.97, H + 1.8), 1.6, 1.2, 5)
    md += railing(-3.0, 3.2, 3.0, 3.2, H + 2.9, 0.8, 5, PAINT_YELLOW())
    md += railing(-3.0, 7.2, 3.0, 7.2, H + 2.9, 0.8, 5, PAINT_YELLOW())
    md += railing(-3.0, 3.2, -3.0, 7.2, H + 2.9, 0.8, 4, PAINT_YELLOW())
    md += railing(3.0, 3.2, 3.0, 7.2, H + 2.9, 0.8, 4, PAINT_YELLOW())
    join_into(mach, md)
    # 驾驶室(悬挂大梁前端下方)
    cab = box("cab", (0, -6.5, H + 0.55), (2.3, 2.1, 1.7), PAINT_WHITE(), 0.12)
    join_into(cab, [
        box("_cw", (0, -6.62, H + 0.72), (1.95, 1.75, 0.62), GLASS(), 0.06),
        box("_cspot", (0, -7.6, H + 0.2), (0.3, 0.2, 0.15), AMBER(), 0.03),
        # v2: 斜面下前窗 + 足下观察窗 + 顶置空调 + 侧后视镜杆
        box("_cwf", (0, -7.42, H + 0.02), (1.9, 0.05, 0.8), GLASS(), 0.02, rot=(math.radians(-28), 0, 0)),
        box("_cwf2", (0, -7.08, H - 0.32), (1.7, 0.7, 0.05), GLASS(), 0.01),
        box("_cac", (0.55, -6.3, H + 1.5), (0.7, 0.8, 0.24), PAINT_GRAY(), 0.04),
        cyl("_cmirror", (1.02, -7.3, H + 0.95), 0.03, 0.34, METAL_DARK(), 0.005, rot=(0, math.pi / 2, 0)),
    ])
    # 小车(沿大梁往返): 车架 + 行走轮 + 起升卷筒
    trolley = box("trolley", (0, -14, H + 1.05), (2.2, 2.6, 0.75), PAINT_GRAY(), 0.06)
    td = [cyl("_tw", (xx, -14 + yy, H + 1.5), 0.16, 0.14, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0))
          for xx in (-0.85, 0.85) for yy in (-1.0, 1.0)]
    td.append(cyl("_drum", (0, -14, H + 0.62), 0.26, 1.5, METAL_DARK(), 0.03, rot=(math.pi / 2, 0, 0)))
    td.append(box("_tcab", (0.7, -14.8, H + 0.9), (0.6, 0.7, 0.5), PAINT_DARK(), 0.04))
    # v2: 顶部起升滑轮组 + 端部缓冲块 + 牵引销
    td.append(cyl("_tsheave1", (-0.5, -14, H + 1.55), 0.26, 0.16, METAL_DARK(), 0.015, rot=(0, math.pi / 2, 0)))
    td.append(cyl("_tsheave2", (0.5, -14, H + 1.55), 0.26, 0.16, METAL_DARK(), 0.015, rot=(0, math.pi / 2, 0)))
    td.append(box("_tbuf1", (0, -15.32, H + 1.05), (1.6, 0.18, 0.3), PAINT_YELLOW(), 0.03))
    td.append(box("_tbuf2", (0, -12.68, H + 1.05), (1.6, 0.18, 0.3), PAINT_YELLOW(), 0.03))
    td.append(cyl("_tpin", (0, -13.2, H + 1.52), 0.05, 0.3, METAL(), 0.01))
    join_into(trolley, td)
    # 吊具(扭锁 + 警示纹; 钢丝绳独立成件, 顶端锚在小车上, 随小车横移、随吊具伸缩)
    spreader = box("spreader", (0, -14, 7.0), (6.1, 2.4, 0.9), PAINT_YELLOW(), 0.06)
    sd = []
    # v2: 上架(滑轮箱, 钢丝绳实际连接点) + 上架滑轮 + 四角外张导板
    sd.append(box("_headblock", (0, -14, 7.8), (5.2, 1.9, 0.5), PAINT_YELLOW(), 0.05))
    for xx in (-0.91, 0.91):
        for yy in (-15.0, -13.0):
            sd.append(cyl("_hbsheave", (xx, yy, 8.08), 0.2, 0.14, METAL_DARK(), 0.01, rot=(0, math.pi / 2, 0)))
    for xx, sx in ((-2.95, 1), (2.95, -1)):
        for yy in (-15.15, -12.85):
            sd.append(box("_fin", (xx, yy, 6.72), (0.07, 0.85, 0.55), PAINT_YELLOW(), 0.01, rot=(0, sx * math.radians(18), 0)))
    ri = 0
    for xx in (-2.6, 2.6):
        for yy in (-15.0, -13.0):
            sd.append(cone("_twl", (xx, yy, 7.55), 0.12, 0.05, 0.25, METAL_DARK(), 0.01))
            ri += 1
            rod_between(f"rope{ri}", (xx * 0.35, yy, H + 0.72), (xx, yy, 7.5), 0.035, METAL_DARK(), 0.005)
    sd += hazard_stripes((0, -15.21, 7.0), 5.8, 0.5, axis="X")
    join_into(spreader, sd)
    # 小车轨道灯带
    box("rail_glow", (0, -9, H + 1.18), (0.26, 35, 0.07), CYAN(), 0.015)
    export_glb("sts_crane")

# ---------- 资产 3: 风力发电机 ----------

def build_wind_turbine():
    clean()
    # 基础环 + 锚栓
    ring = cyl("base_ring", (0, 0, 0.25), 1.85, 0.5, PAINT_GRAY(), 0.05)
    join_into(ring, bolt_ring((0, 0, 0.52), 1.6, 16, 0.06, 0.1, METAL_DARK()))
    # 塔筒下段(带舱门 + 通风缝)
    tl = cone("tower_low", (0, 0, 5.25), 1.55, 0.98, 10, PAINT_WHITE(), 0.05)
    join_into(tl, [
        box("_door", (0, -1.42, 1.15), (0.75, 0.18, 1.7), PAINT_DARK(), 0.06),
        box("_dh", (0.22, -1.5, 1.15), (0.08, 0.05, 0.25), METAL(), 0.01),
        torus("_flange", (0, 0, 10.2), 0.99, 0.05, PAINT_GRAY()),
        # v2: 门框包边 + 门前踏步 + 塔底平台环 + 塔旁箱变(散热鳍+进线管)
        box("_doorf", (0, -1.45, 1.15), (0.88, 0.06, 1.86), METAL_DARK(), 0.02),
        box("_dstep", (0, -1.85, 0.42), (0.9, 0.55, 0.14), METAL(), 0.02),
        torus("_skirt", (0, 0, 0.6), 1.58, 0.06, PAINT_GRAY()),
        box("_xformer", (2.3, 0.4, 0.85), (1.0, 0.75, 1.3), PAINT_GRAY(), 0.05),
        box("_xf1", (2.3, 0.02, 0.85), (0.8, 0.05, 1.0), METAL_DARK(), 0.008),
        box("_xf2", (2.3, 0.78, 0.85), (0.8, 0.05, 1.0), METAL_DARK(), 0.008),
        pipe("_xfcable", [(1.85, 0.4, 0.5), (1.45, 0.35, 0.35), (1.1, 0.2, 0.5)], 0.05, RUBBER()),
    ])
    # 塔筒上段
    tu = cone("tower_up", (0, 0, 14.6), 0.98, 0.62, 9, PAINT_WHITE(), 0.04)
    tud = [torus("_flange2", (0, 0, 19.05), 0.63, 0.04, PAINT_GRAY())]
    tud += bolt_ring((0, 0, 10.26), 1.02, 12, 0.03, 0.09, METAL_DARK())   # v2: 段间法兰螺栓圈
    tud += bolt_ring((0, 0, 19.1), 0.66, 12, 0.025, 0.08, METAL_DARK())
    # v2: 偏航齿圈 + 三台偏航电机(120° 均布)
    tud.append(torus("_yawring", (0, 0, 19.18), 0.72, 0.07, METAL_DARK()))
    for i in range(3):
        ya = math.radians(i * 120 + 30)
        tud.append(box("_yawm", (math.cos(ya) * 0.72, math.sin(ya) * 0.72, 19.35), (0.2, 0.2, 0.32), PAINT_DARK(), 0.03))
    join_into(tu, tud)
    # 机舱(带散热格栅/风速仪/尾翼)
    nac = box("nacelle", (0, 0.2, 19.6), (1.75, 4.9, 1.8), PAINT_WHITE(), 0.35)
    nd = [
        cyl("_anem", (0, 1.4, 20.85), 0.035, 0.6, METAL(), 0.005),
        sphere("_acup", (0, 1.4, 21.15), 0.09, PAINT_DARK()),
    ]
    nd += vent_slats((0.89, 1.2, 19.7), 1.4, 1.0, 5, rot=(0, 0, 0))
    nd += [box("_tail", (0, 2.7, 19.6), (0.5, 0.35, 0.9), PAINT_GRAY(), 0.06)]
    nd += [box("_seam1", (0, -0.4, 19.62), (1.78, 0.03, 1.82), PAINT_GRAY(), 0.005),
           box("_seam2", (0, 1.4, 19.62), (1.78, 0.03, 1.82), PAINT_GRAY(), 0.005)]
    for i in range(3):   # 尾部散热鳍片
        nd.append(box(f"_fin{i}", (0, 2.45 + i * 0.16, 19.0 - i * 0.1), (1.3 - i * 0.12, 0.1, 0.5), METAL_DARK(), 0.02))
    # v2: 舱顶检修护栏 + 舱顶小吊机 + 风向标 + 尾部吊耳
    nd += railing(-0.7, 0.6, -0.7, 2.5, 20.52, 0.55, 4, PAINT_YELLOW())
    nd += railing(0.7, 0.6, 0.7, 2.5, 20.52, 0.55, 4, PAINT_YELLOW())
    nd.append(cyl("_hoistp", (0.55, 2.2, 20.75), 0.05, 0.6, METAL_DARK(), 0.01))
    nd.append(rod_between("_hoista", (0.55, 2.2, 21.0), (0.55, 2.95, 20.85), 0.04, METAL_DARK(), 0.008))
    nd.append(box("_vane", (0, 0.9, 20.95), (0.04, 0.5, 0.16), METAL(), 0.01))
    nd.append(box("_lug", (0, 2.62, 20.45), (0.14, 0.3, 0.22), METAL_DARK(), 0.02))
    join_into(nac, nd)
    # 轮毂轴心(空对象)
    hub = new_empty("hub", (0, -2.4, 19.6))
    cap = cone("hub_cap", (0, -2.75, 19.6), 0.62, 0.08, 1.3, PAINT_WHITE(), 0.04, rot=(math.pi / 2, 0, 0))
    join_into(cap, [cyl("_hub", (0, -2.3, 19.6), 0.58, 0.7, PAINT_GRAY(), 0.05, rot=(math.pi / 2, 0, 0))])
    parent_keep_world(cap, hub)
    # 叶片 v2: 分四段变截面(叶根圆柱段→主梁帽宽弦段→气动过渡段→尖段), 对标真实叶型平面形;
    # 叶根节圆(变桨轴承) + 叶尖红色警示段。绕轮毂 120° 均布, 全部挂 hub 空对象(旋转动画寻址)
    for i in range(3):
        a = math.radians(i * 120 + 90)
        dx, dz = math.cos(a), math.sin(a)
        rot = (0, math.pi / 2 - a, 0)
        secs = [
            # (距毂心, 段长, 根半径, 尖半径, Y 向压扁率, 材质)
            (0.55, 0.9, 0.38, 0.38, 1.0, METAL()),        # 变桨轴承节圆
            (1.7, 1.6, 0.34, 0.30, 1.0, PAINT_WHITE()),   # 叶根圆柱段
            (4.6, 4.5, 0.30, 0.22, 0.46, PAINT_WHITE()),  # 主梁帽宽弦段(翼型最宽)
            (9.1, 4.5, 0.22, 0.13, 0.34, PAINT_WHITE()),  # 气动过渡段
            (12.95, 3.2, 0.13, 0.05, 0.26, PAINT_WHITE()),# 尖段
            (14.95, 0.9, 0.05, 0.015, 0.3, RED()),        # 叶尖警示
        ]
        blade = None
        parts = []
        for di, (dist, ln, r1, r2, flat, mtr) in enumerate(secs):
            sec = cone(f"_bs{di}", (0, 0, 0), r1, r2, ln, mtr, 0.012)
            sec.scale = (1, flat, 1)
            bpy.ops.object.select_all(action="DESELECT")
            sec.select_set(True)
            bpy.context.view_layer.objects.active = sec
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            sec.rotation_euler = rot
            sec.location = (dx * dist, -2.55, 19.6 + dz * dist)
            if di == 1:
                blade = sec
                blade.name = f"blade{i}"   # 主承载段当部件主件(原名沿用, 动画/清单不变)
            else:
                parts.append(sec)
        join_into(blade, parts)
        parent_keep_world(blade, hub)
    # 航空障碍灯
    cyl("beacon", (0, 1.9, 20.65), 0.1, 0.25, REDG(), 0.02)
    export_glb("wind_turbine")

# ---------- 资产 4: 堆垛机 ----------

def build_stacker_crane():
    clean()
    # 双立柱(带底板/螺栓/加强筋, 右柱带爬梯; 对标 AS/RS: 柱高/柱距 ≈15, 加高到 16m)
    for side, x in (("mast_l", -0.55), ("mast_r", 0.55)):
        mast = box(side, (x, 0, 8.0), (0.45, 0.62, 16.0), IND_BLUE(), 0.04)
        md = [
            box("_mpl", (x, 0, 0.14), (0.85, 0.95, 0.16), PAINT_DARK(), 0.02),
            box("_rib1", (x, 0.34, 8.0), (0.12, 0.08, 15.0), PAINT_GRAY(), 0.015),
            box("_rib2", (x, -0.34, 8.0), (0.12, 0.08, 15.0), PAINT_GRAY(), 0.015),
        ]
        md += bolt_ring((x, 0, 0.24), 0.32, 4, 0.035, 0.06, METAL_DARK())
        if side == "mast_r":
            md += ladder(x + 0.28, 0, 0.6, 15.4)
        # v2: 翼缘立唇(前后缘全高) + 内侧载货台导向光轨 + 横隔板(每 2m) + 柱脚三角肋 + 柱脚警示纹
        inner = 0.325 if x < 0 else -0.325
        for yy in (-0.335, 0.335):
            md.append(box("_lip", (x, yy, 8.0), (0.5, 0.05, 15.9), PAINT_GRAY(), 0.01))
        md.append(box("_grail", (x + inner, 0, 8.0), (0.07, 0.24, 15.5), METAL(), 0.012))
        for i in range(7):
            zz = 2.2 + i * 2.1
            md.append(box("_diaph", (x, 0, zz), (0.52, 0.68, 0.09), PAINT_GRAY(), 0.012))
        for yy in (-0.36, 0.36):
            md.append(rod_between("_gus", (x, yy, 0.28), (x, yy * 0.6, 1.5), 0.09, PAINT_GRAY(), 0.015))
        md += hazard_stripes((x, -0.34, 1.1), 0.5, 0.3, axis="X")
        join_into(mast, md)
    # 提升皮带(双柱内侧面全程, 静带 —— 真机皮带过载货台改向轮, 台面移动时视觉上仍连续)
    for x in (-0.325, 0.325):
        box("_hbelt", (x, 0, 8.1), (0.045, 0.09, 15.2), RUBBER(), 0.008)
    # 顶部横梁
    tie = box("top_tie", (0, 0, 15.95), (1.75, 0.75, 0.55), IND_BLUE(), 0.05)
    join_into(tie, [box("_tpl1", (-0.62, 0, 15.95), (0.12, 0.7, 0.62), PAINT_DARK(), 0.02),
                    box("_tpl2", (0.62, 0, 15.95), (0.12, 0.7, 0.62), PAINT_DARK(), 0.02),
                    # v2: 起升电机+卷筒+导向惰轮+顶部警示灯
                    box("_hmotor", (-0.35, 0.55, 15.95), (0.6, 0.5, 0.5), PAINT_DARK(), 0.05),
                    cyl("_hdrum", (0.42, 0.52, 15.95), 0.2, 0.5, METAL_DARK(), 0.02, rot=(math.pi / 2, 0, 0)),
                    cyl("_hidler", (0, 0.4, 15.6), 0.12, 0.3, METAL(), 0.015, rot=(math.pi / 2, 0, 0)),
                    sphere("_tbeacon", (0, 0, 16.35), 0.09, AMBER())])
    # 底部行走台车(车轮/减速箱/缓冲器/警示纹一体化)
    bogie = box("bogie", (0, 0, 0.52), (2.1, 1.45, 0.75), PAINT_DARK(), 0.08)
    bd = [
        cyl("_gear", (0.95, 0, 0.75), 0.28, 0.35, METAL_DARK(), 0.03, rot=(0, math.pi / 2, 0)),
        cyl("_buf1", (-1.12, 0, 0.5), 0.12, 0.18, RUBBER(), 0.02, rot=(0, math.pi / 2, 0)),
        cyl("_buf2", (1.12, 0, 0.5), 0.12, 0.18, RUBBER(), 0.02, rot=(0, math.pi / 2, 0)),
    ]
    bd += hazard_stripes((0, -0.74, 0.52), 1.9, 0.3)
    # v2: 台车驱动电机 + 端部导向轮 + 电缆引入
    bd.append(box("_drive", (-0.6, 0.5, 0.82), (0.55, 0.45, 0.4), PAINT_GRAY(), 0.05))
    bd.append(cyl("_drivem", (-0.6, 0.78, 0.82), 0.16, 0.3, PAINT_DARK(), 0.02, rot=(math.pi / 2, 0, 0)))
    join_into(bogie, bd)
    for x in (-0.72, 0.72):
        for y in (-0.52, 0.52):
            wheel(f"wheel{x}_{y}", (x, y, 0.24), 0.24, 0.16, axis="Y")
    # v2: 操作面板(左柱脚前: 柜体 + 彩屏 + 急停)
    panel = box("panel", (-1.25, -0.42, 1.45), (0.55, 0.28, 0.85), PAINT_GRAY(), 0.04)
    join_into(panel, [
        box("_pscreen", (-1.25, -0.57, 1.62), (0.38, 0.03, 0.28), CYAN(), 0.01),
        cyl("_pestop", (-1.25, -0.58, 1.28), 0.05, 0.06, REDG(), 0.01, rot=(math.pi / 2, 0, 0)),
        box("_pbase", (-1.25, -0.42, 1.0), (0.4, 0.24, 0.06), PAINT_DARK(), 0.01),
    ])
    # 载货台(护板 + 光电传感器)
    carr = box("carriage", (0, 0, 4.6), (0.6, 1.05, 0.45), PAINT_GRAY(), 0.05)
    join_into(carr, [
        box("_cg1", (-0.28, 0, 4.95), (0.05, 1.05, 0.5), PAINT_DARK(), 0.015),
        box("_cg2", (0.28, 0, 4.95), (0.05, 1.05, 0.5), PAINT_DARK(), 0.015),
        cyl("_eye", (0, 0.56, 4.42), 0.045, 0.06, CYAN(), 0.008, rot=(math.pi / 2, 0, 0)),
        # v2: 上下横梁 + 侧向导轮(压立柱光轨) + 货叉挂板 + 靠背栅
        box("_ctop", (0, 0, 5.05), (0.72, 1.0, 0.12), PAINT_GRAY(), 0.02),
        box("_cbot", (0, 0, 4.32), (0.72, 1.0, 0.12), PAINT_GRAY(), 0.02),
        cyl("_gr1", (-0.36, 0, 5.0), 0.09, 0.09, METAL_DARK(), 0.012, rot=(math.pi / 2, 0, 0)),
        cyl("_gr2", (0.36, 0, 5.0), 0.09, 0.09, METAL_DARK(), 0.012, rot=(math.pi / 2, 0, 0)),
        cyl("_gr3", (-0.36, 0, 4.35), 0.09, 0.09, METAL_DARK(), 0.012, rot=(math.pi / 2, 0, 0)),
        cyl("_gr4", (0.36, 0, 4.35), 0.09, 0.09, METAL_DARK(), 0.012, rot=(math.pi / 2, 0, 0)),
        box("_fsh1", (0.14, 0.52, 4.9), (0.22, 0.08, 0.72), METAL_DARK(), 0.015),
        box("_fsh2", (-0.14, 0.52, 4.9), (0.22, 0.08, 0.72), METAL_DARK(), 0.015),
        box("_back1", (0, -0.48, 5.35), (0.7, 0.05, 0.08), METAL(), 0.01),
        box("_back2", (0, -0.48, 5.6), (0.7, 0.05, 0.08), METAL(), 0.01),
    ])
    box("fork_l", (0.14, 0.95, 4.55), (0.15, 1.15, 0.09), METAL(), 0.02)
    box("fork_r", (-0.14, 0.95, 4.55), (0.15, 1.15, 0.09), METAL(), 0.02)
    # 拖链(沿立柱侧面全高: 槽型导轨 + 链节; 原仅 6m, 载货台升顶时像断链)
    box("_chaintray", (0.86, 0, 8.1), (0.2, 0.3, 15.4), PAINT_DARK(), 0.02)
    links = []
    n = 52
    for i in range(n):
        zz = 0.6 + i * (14.9 / n)
        links.append(box(f"_cl{i}", (0.86, 0, zz), (0.14, 0.24, 0.12), METAL_DARK(), 0.02))
    chain = links[0]
    chain.name = "chain"
    join_into(chain, links[1:])
    # 状态灯带
    box("stripe", (0, -0.34, 7.9), (0.2, 0.06, 13.8), CYAN(), 0.015)
    export_glb("stacker_crane")

# ---------- 资产 5: 无人集卡(无驾驶室 Q-Truck 形态) ----------

def build_truck():
    clean()
    # 底盘(侧裙 + 反光标 + 牵引销)
    ch = box("chassis", (0, 0, 0.55), (6.7, 2.2, 0.42), PAINT_DARK(), 0.08)
    cd = [
        box("_sk1", (-0.3, 1.06, 0.5), (5.6, 0.1, 0.4), PAINT_GRAY(), 0.03),
        box("_sk2", (-0.3, -1.06, 0.5), (5.6, 0.1, 0.4), PAINT_GRAY(), 0.03),
        cyl("_pin", (-0.7, 0, 0.8), 0.09, 0.1, METAL(), 0.01),
    ]
    for i in range(3):
        cd.append(box(f"_rf{i}", (-2.4 + i * 2.2, 1.12, 0.55), (0.3, 0.03, 0.08), AMBER(), 0.008))
        cd.append(box(f"_rfb{i}", (-2.4 + i * 2.2, -1.12, 0.55), (0.3, 0.03, 0.08), AMBER(), 0.008))
    join_into(ch, cd)
    # 载货平板 + 扭锁
    deck = box("deck", (-0.75, 0, 0.92), (5.1, 2.3, 0.16), PAINT_GRAY(), 0.03)
    dd = []
    for xx in (-3.05, 1.55):
        for yy in (-1.0, 1.0):
            dd.append(cone("_tw", (xx, yy, 1.06), 0.1, 0.04, 0.16, METAL(), 0.01))
    dd += [box("_dr1", (-0.75, 1.08, 1.0), (5.0, 0.08, 0.1), METAL_DARK(), 0.015),
           box("_dr2", (-0.75, -1.08, 1.0), (5.0, 0.08, 0.1), METAL_DARK(), 0.015)]
    for i in range(7):   # 平板防滑棱纹
        dd.append(box(f"_tread{i}", (-0.75, -0.9 + i * 0.3, 1.005), (5.0, 0.05, 0.025), PAINT_DARK(), 0.004))
    join_into(deck, dd)
    # 前传感舱(无驾驶室: 激光雷达 + 视觉模组 + 天线)
    pod = box("pod", (2.8, 0, 1.39), (1.15, 2.05, 1.25), PAINT_WHITE(), 0.16)
    pd = [
        box("_glass", (3.36, 0, 1.59), (0.08, 1.7, 0.5), GLASS(), 0.03),
        cyl("_lidar", (2.8, 0, 2.11), 0.15, 0.18, METAL_DARK(), 0.02),
        torus("_liring", (2.8, 0, 2.21), 0.13, 0.02, CYAN()),
        cyl("_ant1", (2.45, 0.75, 2.29), 0.015, 0.5, METAL_DARK(), 0.003),
        cyl("_ant2", (2.45, -0.75, 2.29), 0.015, 0.5, METAL_DARK(), 0.003),
        sphere("_cam1", (3.3, 0.65, 1.24), 0.055, GLASS()),
        sphere("_cam2", (3.3, -0.65, 1.24), 0.055, GLASS()),
        box("_pstripe", (2.8, 0, 0.81), (1.0, 2.06, 0.08), CYAN(), 0.02),
    ]
    join_into(pod, pd)
    # 侧挂电池仓(带散热格栅)
    for side, y in (("battery_l", 1.02), ("battery_r", -1.02)):
        bat = box(side, (-0.6, y, 0.62), (2.9, 0.42, 0.55), PAINT_BLUE(), 0.05)
        bd = [box(f"_bv{i}", (-1.7 + i * 0.75, y + (0.22 if y > 0 else -0.22), 0.62), (0.5, 0.04, 0.35), METAL_DARK(), 0.01)
              for i in range(3)]
        join_into(bat, bd)
    # 车轮(三轴)
    axles = (-2.35, -1.25, 1.7)
    wi = 0
    for x in axles:
        for y in (-1.02, 1.02):
            wi += 1
            wheel(f"w{wi}", (x, y, 0.46), 0.46, 0.3, axis="Y")
    # 前后灯带
    box("lightbar_f", (3.4, 0, 0.58), (0.08, 1.85, 0.12), CYAN(), 0.02)
    # v2: 后防撞梁 + 驱动桥挡泥皮 + 尾部气电接口面板(红/黄螺旋接头)
    join_into(ch, [
        box("_rrguard", (-3.38, 0, 0.42), (0.14, 2.05, 0.28), PAINT_GRAY(), 0.03),
        box("_mud1", (-2.98, 1.02, 0.38), (0.06, 0.36, 0.45), RUBBER(), 0.01),
        box("_mud2", (-2.98, -1.02, 0.38), (0.06, 0.36, 0.45), RUBBER(), 0.01),
        box("_gladp", (-3.44, 0.55, 0.78), (0.06, 0.7, 0.4), PAINT_DARK(), 0.015),
        torus("_gladr", (-3.5, 0.38, 0.85), 0.09, 0.025, REDG(), rot=(0, math.pi / 2, 0)),
        torus("_glady", (-3.5, 0.72, 0.85), 0.09, 0.025, AMBER(), rot=(0, math.pi / 2, 0)),
    ])
    # 前保险杠黄黑斜纹(并入底盘, 不进部件清单)
    _chevs = []
    for i in range(7):
        _chevs.append(box(f"_chev{i}", (3.37, -0.85 + i * 0.28, 0.34), (0.03, 0.24, 0.14),
            PAINT_YELLOW() if i % 2 == 0 else PAINT_DARK(), 0.005, rot=(math.radians(42), 0, 0)))
    join_into(ch, _chevs)
    # 传感舱两侧绿饰条 + 顶部四角琥珀示宽灯(并入传感舱)
    _podx = [
        box("_gacc1", (2.85, 1.04, 1.15), (0.75, 0.03, 0.18), IND_GREEN(), 0.01, rot=(0, math.radians(-18), 0)),
        box("_gacc2", (2.85, -1.04, 1.15), (0.75, 0.03, 0.18), IND_GREEN(), 0.01, rot=(0, math.radians(-18), 0)),
        # v2: 前向低位毫米波雷达暗带 + 侧散热格栅 + 充电口盖板 + 顶部旋转警示灯
        box("_radar", (3.38, 0, 0.98), (0.05, 1.3, 0.22), PAINT_DARK(), 0.015),
        box("_pvent1", (2.4, 1.045, 1.55), (0.55, 0.03, 0.3), METAL_DARK(), 0.008),
        box("_pvent2", (2.4, -1.045, 1.55), (0.55, 0.03, 0.3), METAL_DARK(), 0.008),
        box("_charge", (2.15, -1.05, 1.05), (0.34, 0.04, 0.3), PAINT_GRAY(), 0.015),
        cyl("_chargepin", (2.15, -1.08, 1.05), 0.06, 0.05, METAL_DARK(), 0.008, rot=(math.pi / 2, 0, 0)),
        sphere("_beacon", (2.35, 0, 2.3), 0.09, AMBER()),
        cyl("_beaconb", (2.35, 0, 2.24), 0.11, 0.05, PAINT_DARK(), 0.01),
    ]
    for yy in (-0.92, 0.92):
        for xx in (2.35, 3.25):
            _podx.append(box("_mk", (xx, yy, 2.03), (0.08, 0.08, 0.06), AMBER(), 0.01))
    join_into(pod, _podx)
    # 驮运 20 尺集装箱(瓦楞侧板; 对标实箱 6.06m: 4.4→5.8): 整车立刻有作业感
    cont = box("container", (-0.05, 0, 1.88), (5.8, 2.2, 1.6), CONT_BLUE(), 0.03)
    cd3 = []
    for i in range(15):
        xx = -2.75 + i * 0.37
        cd3.append(box(f"_cor{i}", (xx, 1.12, 1.88), (0.1, 0.06, 1.5), NAVY(), 0.008))
        cd3.append(box(f"_corb{i}", (xx, -1.12, 1.88), (0.1, 0.06, 1.5), NAVY(), 0.008))
    # v2: 箱门移到车尾(原来在传感舱侧, 实箱箱门朝后) + 四根门杠 + 门锁凸台 + CSC 铭牌
    cd3.append(box("_cdoor", (-2.96, 0, 1.88), (0.06, 2.1, 1.5), PAINT_GRAY(), 0.01))
    for yy in (-0.88, -0.32, 0.32, 0.88):
        cd3.append(cyl("_dbar", (-3.0, yy, 1.88), 0.032, 1.44, METAL_DARK(), 0.005, verts=10))
        cd3.append(box("_dlock", (-3.04, yy, 1.42), (0.08, 0.14, 0.2), METAL_DARK(), 0.01))
    cd3.append(box("_csc", (-3.0, 0.62, 2.3), (0.04, 0.4, 0.28), PAINT_WHITE(), 0.005))
    # v2: 八只 ISO 角件(集装箱最具识别度的结构件)
    for xx in (-2.9, 2.8):
        for yy in (-1.05, 1.05):
            for zz in (1.16, 2.6):
                cd3.append(box("_ccast", (xx, yy, zz), (0.18, 0.16, 0.15), METAL_DARK(), 0.02))
    cd3.append(box("_cmark", (-0.05, 1.14, 2.33), (1.6, 0.03, 0.35), PAINT_WHITE(), 0.005))
    join_into(cont, cd3)
    box("lightbar_r", (-3.4, 0, 0.58), (0.08, 1.85, 0.12), REDG(), 0.02)
    export_glb("truck")

# ---------- 资产 6: 分拣流水线(辊筒输送 + 扫描门 + 拨杆分流) ----------

def build_sorting_line():
    clean()
    # Isaac ConveyorBelt_A08 直辊筒机(2.72m/节 ×3): 机架一体 + 36 根独立辊筒(运行时转动)
    # 教训: A01 是 90° 弯机(bbox 看不出形状, 缩略图才暴露), 选型必须先看缩略图
    SRC = os.path.join(ROOT, "tools", "conv_a08", "conv_a08.usd")
    bpy.ops.wm.usd_import(filepath=SRC, import_textures_mode="IMPORT_PACK")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    frame = next(o for o in meshes if "Roller" not in o.name and "Decal" not in o.name and "Rubberband" not in o.name)
    decal = next((o for o in meshes if "Decal" in o.name), None)
    rollers = sorted([o for o in meshes if "Roller" in o.name], key=lambda o: o.name)
    rubbers = sorted([o for o in meshes if "Rubberband" in o.name], key=lambda o: o.name)
    for o in [o for o in bpy.data.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()
    frame.name = "conveyor"
    if decal:
        join_into(frame, [decal])
    frame.data.name = "_frame"   # 图元名走 _ 前缀(导出按材质拆 prim 时不会泄成独立部件)
    # USD 材质网络(自定义 OmniPBR)进不了 Blender, 全部落成灰 0.8:
    # 按官方缩略图重建材质节点树(蓝漆机架/拉丝铝辊/黑胶带), 否则整线发灰像素坯
    def set_pbr(name, color, metal, rough):
        m = bpy.data.materials.get(name)
        if not m:
            return
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf.inputs["Base Color"].default_value = (*color, 1)
        bsdf.inputs["Metallic"].default_value = metal
        bsdf.inputs["Roughness"].default_value = rough
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    set_pbr("Aluminium_Brushed_A", (0.78, 0.79, 0.81), 0.95, 0.3)
    set_pbr("Steel_A", (0.6, 0.62, 0.65), 0.9, 0.35)
    set_pbr("MetalPainted_Blue_Glossy_A", (0.11, 0.27, 0.55), 0.25, 0.32)
    set_pbr("MetalPainted_Black_Glossy_A", (0.05, 0.05, 0.06), 0.3, 0.35)
    set_pbr("MetalPainted_Gray_Glossy_A", (0.45, 0.47, 0.5), 0.35, 0.4)
    set_pbr("Metal_Rough_A", (0.5, 0.52, 0.55), 0.85, 0.6)
    set_pbr("Metal_Glossy_A", (0.7, 0.72, 0.75), 0.95, 0.25)
    set_pbr("Plastic_Gray_A", (0.5, 0.5, 0.5), 0.0, 0.6)
    set_pbr("Plastic_Red_A", (0.7, 0.08, 0.05), 0.0, 0.5)
    set_pbr("Plastic_Blue_A", (0.1, 0.3, 0.65), 0.0, 0.5)
    set_pbr("Plastic_Yellow_A", (0.95, 0.7, 0.1), 0.0, 0.5)
    set_pbr("Plastic_Orange_A", (0.9, 0.45, 0.08), 0.0, 0.5)
    set_pbr("Plastic_Rough_Black_A", (0.04, 0.04, 0.045), 0.0, 0.85)
    set_pbr("Acrylic_Clear_Glossy_Blue_A", (0.4, 0.6, 0.9), 0.1, 0.12)
    set_pbr("M_ConveyorBelt_A01_Trim", (0.08, 0.08, 0.09), 0.2, 0.5)
    # 警示贴花带官方 Alpha 贴图(黄黑警示条), 重建节点接 Albedo+Alpha 走 MASK 镂空
    dm = bpy.data.materials.get("M_ConveyorBelt_A01_Decal")
    if dm:
        dm.use_nodes = True
        nt = dm.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        img = bpy.data.images.load(os.path.join(ROOT, "tools", "conv_a08", "Textures", "T_ConveyorsBelt_A01_Decal_Albedo.png"))
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
        dm.blend_method = "CLIP"
    # 辊筒挂为机架子件: 爆炸随机架整体走, 部件清单不重复计数, 运行时逐根转
    for i, r in enumerate(rollers):
        r.name = f"_r{i:02d}"
        bpy.context.view_layer.objects.active = r
        r.select_set(True)
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")   # 原点归几何中心: 否则绕世界原点甩飞
        r.select_set(False)
        r.parent = frame
        r.matrix_parent_inverse = Matrix.Identity(4)
    # 驱动皮带(辊筒下的传动胶带)同样挂机架: 不动画但也不能散落成部件
    for i, r in enumerate(rubbers):
        r.name = f"_rb{i:02d}"
        r.parent = frame
        r.matrix_parent_inverse = Matrix.Identity(4)
    # 机架居世界原点(A08 出厂已落地 zmin=0), 量中线供整组摆位
    fb = [frame.matrix_world @ Vector(c) for c in frame.bound_box]
    cx = (max(v.x for v in fb) + min(v.x for v in fb)) / 2
    cy = (max(v.y for v in fb) + min(v.y for v in fb)) / 2
    sec = [frame]
    kids = rollers + rubbers
    for i in (1, 2):   # 整组链接复制(网格共享), 子件关系随复制保持
        bpy.ops.object.select_all(action="DESELECT")
        frame.select_set(True)
        for r in kids:
            r.select_set(True)
        bpy.context.view_layer.objects.active = frame
        bpy.ops.object.duplicate(linked=True)
        cpy = next(o for o in bpy.context.selected_objects if o.type == "MESH" and o.parent is None)
        sec.append(cpy)
    for i, s in enumerate(sec):
        s.name = f"conveyor{i+1}"
        s.location.x = (i - 1) * 2.72 - cx
        s.location.y = -cy
    # 辊筒面实测高 0.769(A08 辊筒顶), 附件全部按此对齐
    BELT = 0.769
    # 扫描门架(立柱落地 + 顶梁 + 扫描光带 + 相机; 梁底净空过最高包裹 0.32+余量)
    arch = box("arch", (0.6, -0.66, 0.75), (0.16, 0.16, 1.5), PAINT_WHITE(), 0.04)
    ad = [box("_p2", (0.6, 0.66, 0.75), (0.16, 0.16, 1.5), PAINT_WHITE(), 0.04),
          box("_beam", (0.6, 0, 1.42), (0.22, 1.5, 0.24), PAINT_WHITE(), 0.05),
          box("_scan", (0.6, 0, 1.3), (0.08, 1.15, 0.06), CYAN(), 0.01),
          sphere("_cam", (0.6, 0, 1.24), 0.07, GLASS()),
          box("_aps", (0.6, -0.66, 1.55), (0.1, 0.1, 0.06), AMBER(), 0.01)]
    join_into(arch, ad)
    # 分拣拨杆(铰接空轴, 运行时摆动; 臂底与辊筒面平齐才能拨到包裹)
    div = new_empty("diverter", (1.7, -0.8, BELT + 0.12))
    arm = box("diverter_arm", (1.7, -0.15, BELT + 0.15), (0.09, 1.3, 0.3), PAINT_YELLOW(), 0.025)
    join_into(arm, [cyl("_hinge", (1.7, -0.8, BELT + 0.12), 0.09, 0.42, METAL_DARK(), 0.02),
                    box("_astrip", (1.7, -0.15, BELT + 0.32), (0.1, 1.24, 0.04), PAINT_DARK(), 0.008)])
    parent_keep_world(arm, div)
    # 分流滑道(面比辊筒面低 5cm 接件, 支腿落地 + 侧挡)
    chute = box("chute", (2.3, 0.98, BELT - 0.09), (2.0, 0.72, 0.08), METAL_DARK(), 0.03)
    cd = [box("_cg1", (2.3, 1.32, BELT + 0.01), (2.0, 0.05, 0.14), PAINT_GRAY(), 0.015),
          box("_cg2", (2.3, 0.64, BELT + 0.01), (2.0, 0.05, 0.14), PAINT_GRAY(), 0.015)]
    for x in (1.5, 3.1):
        cd.append(box("_cleg", (x, 0.98, (BELT - 0.09) / 2), (0.12, 0.12, BELT - 0.09), PAINT_DARK(), 0.02))
    join_into(chute, cd)
    # 控制柜(柜体 + 斜面屏 + 按钮 + 格栅)
    cab = box("cabinet", (-1.9, 1.05, 0.72), (0.7, 0.5, 1.35), PAINT_GRAY(), 0.05)
    cd2 = [box("_scr", (-1.9, 0.82, 1.28), (0.44, 0.06, 0.3), CYAN(), 0.015, rot=(math.radians(-18), 0, 0)),
           box("_door", (-1.9, 1.31, 0.6), (0.56, 0.03, 0.7), PAINT_DARK(), 0.015),
           cyl("_btn1", (-2.05, 0.79, 1.05), 0.03, 0.03, REDG(), 0.006, rot=(math.pi / 2, 0, 0)),
           cyl("_btn2", (-1.9, 0.79, 1.05), 0.03, 0.03, AMBER(), 0.006, rot=(math.pi / 2, 0, 0)),
           cyl("_btn3", (-1.75, 0.79, 1.05), 0.03, 0.03, CYAN(), 0.006, rot=(math.pi / 2, 0, 0))]
    cd2 += vent_slats((-1.9, 1.31, 1.0), 0.45, 0.35, 4, rot=(math.pi / 2, 0, 0))
    join_into(cab, cd2)
    # 三色警示灯柱(灯罩独立成件, 运行时可点名亮灭)
    tower = cyl("tower", (-1.9, 1.05, 1.72), 0.035, 0.75, METAL_DARK(), 0.008)
    join_into(tower, [cyl("_tbase", (-1.9, 1.05, 1.38), 0.09, 0.06, PAINT_DARK(), 0.015)])
    cyl("lamp_r", (-1.9, 1.05, 2.12), 0.075, 0.14, REDG(), 0.02)
    cyl("lamp_y", (-1.9, 1.05, 1.98), 0.075, 0.14, AMBER(), 0.02)
    cyl("lamp_g", (-1.9, 1.05, 1.84), 0.075, 0.14, CYAN(), 0.02)
    # 包裹(纸箱 + 胶带; 不参与拆解, 运行时沿线体流动; 箱底落在辊筒面上)
    # 真线是混流: 四件四种尺寸, 胶带按比例贴顶
    PKGS = [(0.42, 0.34, 0.28), (0.36, 0.30, 0.24), (0.50, 0.38, 0.32), (0.32, 0.27, 0.22)]
    for i, (w, d, h) in enumerate(PKGS):
        x = -2.5 + i * 1.3
        pkg = box(f"pkg{i+1}", (x, 0, BELT + h / 2), (w, d, h), mat(f"card{i}", (0.55 + i * 0.03, 0.42, 0.26), 0.0, 0.75), 0.025)
        join_into(pkg, [box("_tape", (x, 0, BELT + h + 0.011), (w + 0.01, d * 0.3, 0.022), PAINT_BLUE(), 0.006)])
    export_glb("sorting_line")

# ---------- 资产 7: 叉车(Isaac 真机 CAD, 货叉可动) ----------

def build_forklift():
    clean()
    # NVIDIA Isaac forklift.usd(37 万顶点): 车体/货叉天然分件
    # 替换 Gazebo Fuel 刚性模型(单网格不可动) —— 货叉升降 + 低位移位才有作业感
    # 注意: Blender USD 导入不还原 OmniPBR 贴图(只有空壳材质), PBR 三件套手动接
    SRC = os.path.join(ROOT, "tools", "isaac_forklift", "forklift.usd")
    TEX = os.path.join(ROOT, "tools", "isaac_forklift", "Materials", "Textures")
    bpy.ops.wm.usd_import(filepath=SRC)
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    body = next(o for o in meshes if "Body" in o.name)
    fork = next(o for o in meshes if "Fork" in o.name and "Body" not in o.name)
    for o in [o for o in bpy.data.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # 货叉原点归几何中心(≈门架铰点): 否则后倾动画绕世界原点把货叉甩下门架(与辊筒同款坑)
    bpy.ops.object.select_all(action="DESELECT")
    fork.select_set(True)
    bpy.context.view_layer.objects.active = fork
    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.context.view_layer.update()
    body.name = "body"
    fork.name = "fork"
    # 手动重建 OmniPBR: D=基色 N=法线 ORM=遮蔽/粗糙/金属(glTF 同构)
    pbr = bpy.data.materials.new("forklift_pbr")
    pbr.use_nodes = True
    nt = pbr.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    def img_node(name, non_color=False):
        img = bpy.data.images.load(os.path.join(TEX, name))
        if non_color:
            img.colorspace_settings.name = "Non-Color"
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        return n
    nt.links.new(img_node("T_Forklift_D.png").outputs["Color"], bsdf.inputs["Base Color"])
    orm = img_node("T_Forklift_ORM.png", True)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(orm.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    nrm = img_node("T_Forklift_N.png", True)
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nrm.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    for o in (body, fork):
        o.data.materials.clear()
        o.data.materials.append(pbr)
        if not o.data.uv_layers:
            print("WARN no UV on", o.name)
    # 整体落地(车底 zmin=0)
    zs = [body.matrix_world @ Vector(c) for c in body.bound_box]
    zmin = min(v.z for v in zs)
    for o in (body, fork):
        o.location.z -= zmin
    bpy.context.view_layer.update()
    # 琥珀警示灯(真机强制配置, 行车时闪烁; 车顶后部)
    bb2 = [body.matrix_world @ Vector(c) for c in body.bound_box]
    top = max(v.z for v in bb2)
    rear = max(v.y for v in bb2)
    bc = cyl("beacon", (0.28, rear - 0.35, top + 0.05), 0.045, 0.1, AMBER(), 0.01, verts=24)
    join_into(bc, [cyl("_bcbase", (0.28, rear - 0.35, top + 0.005), 0.06, 0.03, METAL_DARK(), 0.006, verts=24)])
    # 托盘与载荷随货叉升降(动画里三者 z 同步)
    fb = [fork.matrix_world @ Vector(c) for c in fork.bound_box]
    prong_top = min(v.z for v in fb) + 0.12
    fx = sum(v.x for v in fb) / 8
    fy = max(v.y for v in fb) - 0.7   # 托盘背贴货叉架(留出叉架背板), 不是挂在齿尖上
    wood = mat("wood", (0.52, 0.38, 0.2), 0.0, 0.8)
    pal = box("pallet", (fx, fy, prong_top + 0.07), (1.1, 1.0, 0.14), wood, 0.015)
    join_into(pal, [box(f"_slat{i}", (fx - 0.42 + i * 0.42, fy, prong_top + 0.035), (0.14, 1.0, 0.07), wood, 0.008) for i in range(3)])
    pay = box("payload", (fx, fy, prong_top + 0.14 + 0.3), (0.86, 0.8, 0.6), mat("card_f", (0.58, 0.44, 0.27), 0.0, 0.75), 0.03)
    join_into(pay, [box("_ptape", (fx, fy, prong_top + 0.14 + 0.612), (0.87, 0.24, 0.025), PAINT_BLUE(), 0.006),
                    box("_plabel", (fx + 0.2, fy - 0.405, prong_top + 0.14 + 0.42), (0.3, 0.005, 0.16), PAINT_WHITE(), 0.002)])
    export_glb("forklift")

# ---------- 资产 8: KUKA KR210 六轴工业臂(Isaac 真机 CAD, 运动链自装配) ----------

def build_kr210():
    clean()
    # Isaac KR210_L150(28 万顶点): 节点树是平铺的(运动关系在 USD joint prims 里, 不进节点),
    # 按已测枢轴坐标自建运动链: j1 回转 → j6 法兰, 连杆网格逐节挂点
    SRC = os.path.join(ROOT, "tools", "kr210", "kr210_l150.usd")
    bpy.ops.wm.usd_import(filepath=SRC)
    meshes = sorted([o for o in bpy.data.objects if o.type == "MESH"], key=lambda o: o.name)
    bpy.context.view_layer.update()
    # 关键: USD 网格的世界位置在父节点变换里(自身 location=0), 先把合成世界矩阵烘进顶点
    # 再删父级 —— 直接 transform_apply 只烘自身 TRS(=0), 顶点会留在"源-框架"局部坐标导致整机下沉脱臼
    for m in meshes:
        m.data.transform(m.matrix_world)
        m.parent = None
        m.matrix_parent_inverse = Matrix.Identity(4)
        m.location = (0, 0, 0)
        m.rotation_euler = (0, 0, 0)
        m.scale = (1, 1, 1)
    for o in [o for o in bpy.data.objects if o.type != "MESH"]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()
    # KUKA 涂装: 机身 KUKA 橙, 腕段(4-6 轴)深石墨
    ORANGE = mat("kr_orange", (0.92, 0.33, 0.04), 0.25, 0.42)
    GRAPHITE = mat("kr_graphite", (0.09, 0.1, 0.11), 0.5, 0.38)
    # (关节名, 父, 枢轴(世界), [(网格序号, 材质)] —— 枢轴实测自 USD joint prims
    chain = [
        ("j1", None, (0, 0, 0), [(1, ORANGE)]),
        ("j2", "j1", (-0.003, 0.001, 0.331), [(2, ORANGE)]),
        ("j3", "j2", (0.350, -0.037, 0.750), [(3, ORANGE)]),
        ("j4", "j3", (0.350, -0.184, 2.000), [(4, GRAPHITE)]),
        ("j5", "j4", (1.308, 0, 1.945), [(5, GRAPHITE)]),
        ("j6", "j5", (1.850, 0, 1.945), [(6, GRAPHITE)]),
    ]
    # 连杆网格: visuals(基座) + visuals.001..006(连杆1-6)
    links = [None] * 7
    for m in meshes:
        idx = 0 if m.name == "visuals" else int(m.name.split(".")[-1])
        links[idx] = m
    base = links[0]
    base.name = "link_base"
    base.data.materials.clear()
    base.data.materials.append(ORANGE)
    pos_by_name = {c[0]: c[2] for c in chain}
    empties = {}
    for name, parent, pos, attachments in chain:
        if parent:
            e = new_empty(name, tuple(pos[i] - pos_by_name[parent][i] for i in range(3)))
        else:
            e = new_empty(name, pos)
        if parent:
            e.parent = empties[parent]
            e.matrix_parent_inverse = Matrix.Identity(4)
        empties[name] = e
        for idx, material in attachments:
            link = links[idx]
            link.name = "link" + name[1]
            link.data.materials.clear()
            link.data.materials.append(material)
            for p in link.data.polygons:
                p.use_smooth = True
            parent_keep_world(link, e)   # 网格顶点已是世界坐标: 保位挂载(恒等逆矩阵会把关节位移再叠加一次)
    for p in base.data.polygons:
        p.use_smooth = True
    export_glb("kr210")

import sys
# 单件过滤: Blender -b --python tools/blender_assets.py -- traffic_pole → 只重建这一件
# (全量重建会把 GLB 全部刷成未压缩态, 上次忘了重压缩直接让交付包胀了 50MB)
_only = None
if "--" in sys.argv:
    _only = sys.argv[sys.argv.index("--") + 1].replace("build_", "")
    print("single-asset filter:", _only)
for fn in (build_robot_cell, build_sts_crane, build_wind_turbine, build_stacker_crane, build_truck, build_sorting_line, build_forklift, build_kr210, build_traffic_pole):
    if _only and fn.__name__ != f"build_{_only}":
        continue
    fn()
print("ALL ASSETS DONE" if not _only else f"DONE {_only}")
