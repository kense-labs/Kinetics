# CAD GLB → 可拆解装备: 松散件分离 → 空间规则聚合成装配体 → 导出
# 用法: Blender -b --python tools/convert_cad.py -- <in.glb> <out.glb> <kind>
# kind=forklift: 叉车装配规则(车轮/门架/货叉/护顶架/座椅/车身)
import bpy
import sys
import mathutils
from collections import defaultdict

argv = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT, KIND = argv[0], argv[1], argv[2]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

mesh = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
bpy.context.view_layer.objects.active = mesh
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.separate(type="LOOSE")
bpy.ops.object.mode_set(mode="OBJECT")
parts = [o for o in bpy.context.scene.objects if o.type == "MESH"]
print("loose parts:", len(parts))


def stat(o):
    corners = [o.matrix_world @ mathutils.Vector(c) for c in o.bound_box]
    xs = [c.x for c in corners]; ys = [c.y for c in corners]; zs = [c.z for c in corners]
    return {
        "o": o,
        "size": (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)),
        "ctr": ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, (max(zs) + min(zs)) / 2),
        "tris": len(o.data.polygons),
    }


stats = [stat(o) for o in parts]
groups = defaultdict(list)


def forklift_group(s):
    x, y, z = s["ctr"]; sx, sy, sz = s["size"]
    # 车轮: 贴地 + 四角
    if z < 0.55 and abs(y) > 0.75:
        return "wheel"
    # 门架+货叉: 车头前方区域
    if y < -0.95:
        return "mast"
    # 护顶架: 顶部框架
    if z > 1.35:
        return "guard"
    # 座椅/方向机: 中部座舱区
    if 0.55 < z < 1.35 and abs(y) < 0.55 and sx < 0.5 and sy < 0.5:
        return "cab"
    # 其余并入车身
    return "body"


def tower_group(s):
    x, y, z = s["ctr"]
    # 吊钩组: 起重臂下方悬垂件(远离塔身且在臂高以下)
    if y < -3 and z < 22.5:
        return "hook"
    # 塔身: 中心柱区
    if abs(x) < 2.6 and abs(y) < 2.6 and z < 24:
        return "tower_mast"
    # 起重臂: -Y 方向臂架
    if y < -3:
        return "jib"
    # 平衡臂/配重: +Y 方向
    if y > 3:
        return "counter_jib"
    # 回转平台/塔尖/司机室
    return "platform"


GROUPER = {"forklift": forklift_group, "tower": tower_group}
for s in stats:
    groups[GROUPER[KIND](s)].append(s)

for name, items in groups.items():
    groups[name].sort(key=lambda s: -s["tris"])

# 合并每组
merged_names = []


def merge(name, items):
    if not items:
        return
    bpy.ops.object.select_all(action="DESELECT")
    for it in items:
        it["o"].select_set(True)
    bpy.context.view_layer.objects.active = items[0]["o"]
    bpy.ops.object.join()
    items[0]["o"].name = name
    merged_names.append(name)
    print(f"{name}: {len(items)} loose -> 1, tris={sum(i['tris'] for i in items)}")


if KIND == "tower":
    for nm in ("hook", "tower_mast", "jib", "counter_jib", "platform"):
        merge(nm, groups.get(nm, []))
else:
    merge("body", groups.get("body", []))
    merge("mast", groups.get("mast", []))
    merge("guard", groups.get("guard", []))
    merge("cab", groups.get("cab", []))
    # 车轮: 按前后左右分 4 个
    ws = groups.get("wheel", [])
    if ws:
        quads = defaultdict(list)
        for s in ws:
            x, y = s["ctr"][0], s["ctr"][1]
            quads[("f" if y < 0 else "r", "l" if x < 0 else "r")].append(s)
        i = 0
        for (fr, lr), items in sorted(quads.items()):
            i += 1
            merge(f"w{i}", items)

bpy.ops.export_scene.gltf(filepath=OUT, export_format="GLB", export_apply=True)
print("exported", OUT, "assemblies:", merged_names)
