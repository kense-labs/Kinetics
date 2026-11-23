# 整厂合成: 六台真机设备按真实产线布局摆进车间, 导出一张 factory_floor.glb
# 用法: Blender -b --python tools/compose_factory.py
# 前提: twin-assets 里是**未压缩**件(先跑 blender_assets.py 全量重建; 压缩留给 compress_assets.sh)
# 布局(Z-up, 米): 左端卡口进闸 → 集卡来料道 → 中央分拣线 → 线旁 KR210 机器人单元(带围栏)
#   → 叉车叉取区 → 右端堆垛机立库区; 顶部双桁架灯带。设备组按装备 id 命名供动画寻址。
import bpy
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 合成只读未压缩件(Blender 不认 meshopt 压缩): factory_src 是合成专用源缓存
# (blender_assets.py 重建后、compress_assets.sh 压缩前拷入; voron 等 STEP 件拷 cq 原始导出)
ASSETS = os.path.join(ROOT, "tools", "factory_src")

bpy.ops.wm.read_factory_settings(use_empty=True)

# ---------- 设备导入与摆位 ----------
# (装备 id, 位置(x,y), 朝向 rotZ, 缩放) —— id 即动画寻址名; voron GLB 是毫米单位, 缩到米级
# v2 策展版: 删卡口/集卡/堆垛机, 入库区改三台 Voron 增材工位(我们的旗舰装配体当主角)
ITEMS = [
    ("voron_printer", (3.2, 2.4, 0), 0, 0.0018),      # 增材工位 1(原立库区, 尺度放大到 2.1m 才有存在感)
    ("voron_printer", (4.9, 2.4, 0), 0, 0.0018),      # 增材工位 2
    ("voron_printer", (6.6, 2.4, 0), 0, 0.0018),      # 增材工位 3
    ("sorting_line", (-1.0, 0.0, 0), 0, 1),           # 分拣流水线: 车间中央沿 X
    ("kr210",        (-1.0, -3.4, 0), 0, 1),          # 机器人单元: 线旁上下料(带围栏)
    ("forklift",     (-8.0, -5.2, 0), math.radians(10), 1),  # 叉车: 车道叉取位(左区补位)
]
# 同名机组重名编号(装配树组名必须唯一): voron_printer×3 → voron_1/2/3
_seen = {}
for i, it in enumerate(ITEMS):
    _seen[it[0]] = _seen.get(it[0], 0) + 1
    if it[0] == "voron_printer":
        ITEMS[i] = (f"voron_{_seen[it[0]]}", it[1], it[2], it[3])

def import_group(eid, loc, rotz, scale=1):
    src_id = "voron_printer" if eid.startswith("voron_") else eid   # 同型多机共用一个 GLB
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(ASSETS, src_id + ".glb"))
    new = [o for o in bpy.data.objects if o not in before]
    grp = bpy.data.objects.new(eid, None)
    bpy.context.scene.collection.objects.link(grp)
    grp.location = loc
    grp.rotation_euler = (0, 0, rotz)
    grp.scale = (scale, scale, scale)
    for o in new:
        if o.parent is None:   # 顶层节点挂到组下(局部变换即文件内坐标, 平移全靠组)
            o.parent = grp
            o.matrix_parent_inverse = mathutils_identity()
    return grp

from mathutils import Matrix
def mathutils_identity():
    return Matrix.Identity(4)

groups = [import_group(*it) for it in ITEMS]

# ---------- 车间装修(全部 _ 前缀: 地坪/标线/围栏/灯架 不是部件) ----------
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

FLOOR = mat("f_floor", (0.16, 0.18, 0.21), 0.05, 0.72)
LINE_W = mat("f_linew", (0.75, 0.77, 0.72), 0.0, 0.7)
LINE_Y = mat("f_liney", (0.85, 0.65, 0.10), 0.1, 0.6)
FENCE_Y = mat("f_fence", (0.85, 0.62, 0.06), 0.2, 0.5)
FENCE_D = mat("f_fence_d", (0.12, 0.13, 0.15), 0.4, 0.6)
TRUSS = mat("f_truss", (0.28, 0.30, 0.34), 0.6, 0.42)
LAMP = mat("f_lamp", (0.9, 0.92, 0.9), 0.1, 0.4, (1.0, 0.98, 0.92), 2.2)

def box(name, loc, scale, material, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(location=loc)
    o = bpy.context.object
    o.name = name
    o.scale = (scale[0] / 2, scale[1] / 2, scale[2] / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material: o.data.materials.append(material)
    return o

def cyl(name, loc, r, depth, material, verts=24):
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=depth, location=loc)
    o = bpy.context.object
    o.name = name
    if material: o.data.materials.append(material)
    return o

# 地坪
box("_floor", (0, 0, -0.08), (30, 20, 0.16), FLOOR)
# 注意: 厂区裙地**不进 GLB** —— 大火柴盒会撑爆模型包围盒(爆炸分层/阴影视锥/构图全按 bbox 算),
# 裙地由前端 noStage 分支用代码铺(挂在 stage, 不参与任何 bbox 计算)
# 来料车道标线(双线, 沿 X)
for y in (-6.9, -5.1):
    box("_lane", (-4.5, y, 0.012), (21, 0.12, 0.012), LINE_W)
# 机器人单元安全围栏(四角立柱 + 三面护板, 留线侧开口)
for px, py in [(-2.6, -4.9), (0.6, -4.9), (-2.6, -2.0), (0.6, -2.0)]:
    cyl("_fence_post", (px, py, 0.85), 0.045, 1.7, FENCE_Y, 12)
box("_fence_b", (-1.0, -4.9, 0.85), (3.2, 0.05, 1.5), FENCE_D)
box("_fence_l", (-2.6, -3.45, 0.85), (0.05, 2.9, 1.5), FENCE_D)
box("_fence_r", (0.6, -3.45, 0.85), (0.05, 2.9, 1.5), FENCE_D)
# 增材农场区地面界线(原立库区)
box("_rack_zone", (4.7, 3.0, 0.012), (5.0, 3.2, 0.012), LINE_Y)
# 顶部双桁架灯带(沿 X 两跨)
for zy in (-3.5, 3.5):
    box("_truss", (0, zy, 7.6), (26, 0.22, 0.22), TRUSS)
    box("_lampstrip", (0, zy, 7.46), (25, 0.08, 0.04), LAMP)

# 导出(写回 twin-assets 供前端; 注意 factory_floor.glb 会被压缩覆盖 —— 合成源不受影响)
path = os.path.join(ROOT, "frontend", "public", "twin-assets", "factory_floor.glb")
bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True)
print("exported", path, "objects:", len(bpy.data.objects))
