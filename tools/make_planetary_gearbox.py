# 行星减速器参数化生成(cadquery): 太阳轮/行星轮×3/内齿圈/行星架/输入输出轴系/壳体/紧固件
# 产出双层: ① 直接导出 GLB  ② 导出 STEP(装配树) —— 再用 step_to_glb.py 回读验证管线无损
# 用法: tools/.venv-cad/bin/python tools/make_planetary_gearbox.py <out_dir>
import os
import math
import sys
import cadquery as cq

OUT = sys.argv[1] if len(sys.argv) > 1 else "tools/step_pilot"
os.makedirs(OUT, exist_ok=True)

# ---------- 材料 ----------
ALU = cq.Color(0.62, 0.65, 0.68)      # 铝壳
STEEL = cq.Color(0.42, 0.44, 0.47)    # 钢齿轮
BRIGHT = cq.Color(0.75, 0.78, 0.82)   # 光轴
DARK = cq.Color(0.16, 0.17, 0.19)     # 轴承/紧固件
BRASS = cq.Color(0.55, 0.42, 0.18)    # 保持架

# ---------- 渐开线近似齿形(梯形齿, 展台尺度的视觉真实) ----------
def spur_gear(module, teeth, thickness, bore=0.0, hub_r=0.0):
    """梯形近似齿直齿轮: 分度圆 module*teeth/2, 齿顶 +m, 齿根 -1.25m; 齿以分度点半径为中心对称"""
    pr = module * teeth / 2
    ro, rr = pr + module, pr - 1.25 * module
    pitch = math.tau / teeth
    tw_r, tw_t = pitch * 0.62, pitch * 0.42   # 齿根/齿顶厚(角)
    pts = []
    for i in range(teeth):
        ac = i * pitch + pitch / 2            # 齿中心角
        pts += [(rr, ac - tw_r / 2), (ro, ac - tw_t / 2), (ro, ac + tw_t / 2), (rr, ac + tw_r / 2)]
    pts = [(r * math.cos(a), r * math.sin(a)) for r, a in pts]
    g = cq.Workplane("XY").polyline(pts).close().extrude(thickness)
    if bore > 0:
        g = g.faces(">Z").workplane().hole(bore)
    if hub_r > bore:
        g = g.union(cq.Workplane("XY").circle(hub_r).extrude(thickness))
    return g

def ring_gear(module, teeth, thickness, outer_r):
    """内齿圈: 外圆筒 - 内梯形齿(齿朝圆心)"""
    pr = module * teeth / 2
    ri, ro = pr - module, pr + 1.25 * module
    pitch = math.tau / teeth
    tw_r, tw_t = pitch * 0.58, pitch * 0.44
    pts = []
    for i in range(teeth):
        ac = i * pitch + pitch / 2
        pts += [(ro, ac - tw_r / 2), (ri, ac - tw_t / 2), (ri, ac + tw_t / 2), (ro, ac + tw_r / 2)]
    pts = [(r * math.cos(a), r * math.sin(a)) for r, a in pts]
    teeth_cut = cq.Workplane("XY").polyline(pts).close().extrude(thickness)
    body = cq.Workplane("XY").circle(outer_r).extrude(thickness)
    return body.cut(teeth_cut)

# ---------- 参数(真实行星减速器比例: i = 1 + Zr/Zs) ----------
M = 1.4          # 模数 mm
ZS, ZP, ZR = 18, 21, 60   # i = 1 + 60/18 ≈ 4.33
T = 10.0         # 齿厚
PS, PP, PR_ = M * ZS / 2, M * ZP / 2, M * ZR / 2
ORBIT = PS + PP            # 行星轮轨道半径
RING_OUT = PR_ + 8
BOX_R = RING_OUT + 6       # 壳体半径
H_HALF = 14                # 壳体半高

assy = cq.Assembly(name="planetary_gearbox")

def add(parent, obj, name, loc=(0, 0, 0), color=None):
    parent.add(obj, name=name, loc=cq.Location(cq.Vector(*loc)), color=color)

# ============ 壳体总成 ============
housing = cq.Assembly(name="housing_assy")
shell_l = (cq.Workplane("XY").circle(BOX_R).extrude(H_HALF)
           .faces(">Z").workplane().circle(RING_OUT).cutBlind(-H_HALF + 3))
add(housing, shell_l, "housing_lower", (0, 0, 0), ALU)
shell_u = (cq.Workplane("XY").circle(BOX_R).extrude(H_HALF)
           .faces(">Z").workplane().circle(RING_OUT).cutBlind(-H_HALF + 3)
           .faces(">Z").workplane().hole(26))
add(housing, shell_u, "housing_upper", (0, 0, T + 2 * H_HALF - 2), ALU)   # 倒置扣合(近似)
ring = ring_gear(M, ZR, T, RING_OUT)
add(housing, ring, "ring_gear", (0, 0, H_HALF + 2), STEEL)
# 壳体法兰螺栓 ×8
for i in range(8):
    a = i * math.tau / 8
    bolt = cq.Workplane("XY").circle(2.5).extrude(6).union(
        cq.Workplane("XY").polygon(6, 4.6).extrude(2.6).translate((0, 0, 6)))
    add(housing, bolt, f"flange_bolt_{i+1}", (math.cos(a) * (BOX_R - 3), math.sin(a) * (BOX_R - 3), T + 2 * H_HALF - 2), DARK)
assy.add(housing, name="housing_assy")

# ============ 齿轮系 ============
geartrain = cq.Assembly(name="geartrain")
sun = spur_gear(M, ZS, T, bore=8)
add(geartrain, sun, "sun_gear", (0, 0, H_HALF + 2), STEEL)
for i in range(3):
    a = i * math.tau / 3
    pl = spur_gear(M, ZP, T, bore=5)
    add(geartrain, pl, f"planet_gear_{i+1}", (math.cos(a) * ORBIT, math.sin(a) * ORBIT, H_HALF + 2), STEEL)
assy.add(geartrain, name="geartrain")

# ============ 行星架总成(输出件) ============
carrier = cq.Assembly(name="carrier_assy")
plate_d = H_HALF - 2
for tag, zz in (("plate_lower", H_HALF - 6), ("plate_upper", H_HALF + T + 8)):
    plate = cq.Workplane("XY").circle(PR_ - 4).extrude(3)
    plate = plate.faces(">Z").workplane().hole(16)
    for i in range(3):
        a = i * math.tau / 3
        plate = plate.faces(">Z").workplane().pushPoints([(math.cos(a) * ORBIT, math.sin(a) * ORBIT)]).hole(5.4)
    add(carrier, plate, f"carrier_{tag}", (0, 0, zz), BRIGHT)
for i in range(3):   # 行星销轴 + 滚针套
    a = i * math.tau / 3
    x, y = math.cos(a) * ORBIT, math.sin(a) * ORBIT
    pin = cq.Workplane("XY").circle(2.7).extrude(T + 14)
    add(carrier, pin, f"planet_pin_{i+1}", (x, y, H_HALF - 6), BRIGHT)
    roller = cq.Workplane("XY").circle(4.4).circle(2.9).extrude(T)
    add(carrier, roller, f"needle_race_{i+1}", (x, y, H_HALF + 2), DARK)
out_shaft = cq.Workplane("XY").circle(8).extrude(30)
add(carrier, out_shaft, "output_shaft", (0, 0, H_HALF + T + 10), BRIGHT)
assy.add(carrier, name="carrier_assy")

# ============ 输入轴系 ============
input_assy = cq.Assembly(name="input_assy")
in_shaft = cq.Workplane("XY").circle(4).extrude(H_HALF + T + 6)
add(input_assy, in_shaft, "input_shaft", (0, 0, -8), BRIGHT)
key = cq.Workplane("XY").box(2.2, 2.2, 10)
add(input_assy, key, "shaft_key", (4.6, 0, H_HALF + 4), DARK)
assy.add(input_assy, name="input_assy")

# ============ 轴承 ×4(简化双环+滚珠圈) ============
bearings = cq.Assembly(name="bearings_assy")
def bearing(name, r_out, r_in, w, loc):
    outer = cq.Workplane("XY").circle(r_out).circle(r_out - 2.2).extrude(w)
    inner = cq.Workplane("XY").circle(r_in + 2.2).circle(r_in).extrude(w)
    balls = None
    nb = max(6, int((r_out - r_in) * 1.4))
    for i in range(nb):
        a = i * math.tau / nb
        b = cq.Workplane("XY").sphere((r_out - r_in - 2.2) / 2).translate((math.cos(a) * (r_in + 1.1 + (r_out - r_in - 2.2) / 2), math.sin(a) * (r_in + 1.1 + (r_out - r_in - 2.2) / 2), w / 2))
        balls = b if balls is None else balls.union(b)
    grp = cq.Assembly(name=name)
    add(grp, outer, f"{name}_outer", (0, 0, 0), DARK)
    add(grp, inner, f"{name}_inner", (0, 0, 0), DARK)
    if balls is not None:
        add(grp, balls, f"{name}_balls", (0, 0, 0), BRASS)
    bearings.add(grp, name=name, loc=cq.Location(cq.Vector(*loc)))
bearing("bearing_input", 12, 4.2, 5, (0, 0, -4))
bearing("bearing_input2", 12, 4.2, 5, (0, 0, H_HALF + T + 2))
bearing("bearing_output", 16, 8.2, 6, (0, 0, H_HALF + T + 4))
bearing("bearing_output2", 16, 8.2, 6, (0, 0, 2 * H_HALF + T))
assy.add(bearings, name="bearings_assy")

# ============ 导出: GLB(直接) + STEP(装配树回读验证) ==========
glb_path = os.path.join(OUT, "planetary_gearbox.glb")
step_path = os.path.join(OUT, "planetary_gearbox.step")
assy.export(glb_path, tolerance=0.12, angularTolerance=0.25)
assy.export(step_path)
print("GLB:", glb_path, os.path.getsize(glb_path) // 1024, "KB")
print("STEP:", step_path, os.path.getsize(step_path) // 1024, "KB")
# 统计
leaves, seen, stack = [], set(), [assy]
while stack:
    a = stack.pop()
    if id(a) in seen:
        continue
    seen.add(id(a))
    for n, c in a.objects.items():
        if c.obj is not None:
            leaves.append(n)
        stack.append(c)
print(f"零件 {len(leaves)} 个, 节点 {len(seen)} 个")
