# STEP → GLB 装配树保真转换(cadquery/OCP):
# Assembly.importStep(保留零件名/层级/颜色) → 撞名唯一化 → 微件过滤(垫圈/小螺钉) → 粗网格导出 GLB
# 用法: tools/.venv-cad/bin/python tools/step_to_glb.py <input.step> <output.glb>
# 旋钮(env): TOL=网格挠度mm(默认0.25) ANGTOL=角度容差rad(默认0.4) DROP_DIAG=丢弃包围盒对角线<N mm的微件(默认4, 0=不过滤)
import os
import sys
import time

sys.setrecursionlimit(100000)   # 真实装配体层级很深(整机→模组→零件)

import cadquery as cq

# 真实装配体常有镜像/重复件同名(cadquery 要求装配内唯一名)——猴子补丁: 撞名自动加 #2 后缀
_orig_add = cq.Assembly.add
def _add_uniq(self, arg, **kwargs):
    name = kwargs.get("name") or getattr(arg, "name", None)
    if name and name in self.objects:
        base = name
        i = 2
        while f"{base}#{i}" in self.objects:
            i += 1
        kwargs["name"] = f"{base}#{i}"
    return _orig_add(self, arg, **kwargs)
cq.Assembly.add = _add_uniq


def main():
    src, dst = sys.argv[1], sys.argv[2]
    tol = float(os.environ.get("TOL", "0.25"))
    ang = float(os.environ.get("ANGTOL", "0.4"))
    drop_diag = float(os.environ.get("DROP_DIAG", "4"))
    t0 = time.time()
    print(f"[1/4] importStep: {src}")
    assy = cq.Assembly.importStep(src)
    print(f"      导入完成 {time.time() - t0:.1f}s")

    # 装配树统计(共享子装配有引用环, 迭代 + 按节点 id 去重)
    leaves, seen, stack = [], set(), [assy]
    while stack:
        a = stack.pop()
        if id(a) in seen:
            continue
        seen.add(id(a))
        for name, child in a.objects.items():
            if child.obj is not None:
                leaves.append((a, name, child))
            stack.append(child)
    print(f"[2/4] 装配树: 叶级零件 {len(leaves)} 个, 节点 {len(seen)} 个")

    # 微件过滤(垫圈/小螺钉占掉大半零件数与三角面, 展台尺度下不可见)
    dropped = 0
    if drop_diag > 0:
        for parent, name, child in leaves:
            try:
                bb = child.obj.BoundingBox()
                diag = (bb.xlen ** 2 + bb.ylen ** 2 + bb.zlen ** 2) ** 0.5
            except Exception:
                continue
            if diag < drop_diag:
                del parent.objects[name]
                dropped += 1
        print(f"      微件过滤(<{drop_diag}mm): 丢弃 {dropped}, 剩 {len(leaves) - dropped}")

    print(f"[3/4] 网格化并导出 GLB: {dst} (tol={tol}mm, ang={ang}rad)")
    assy.export(dst, tolerance=tol, angularTolerance=ang)
    sz = os.path.getsize(dst) / 1e6
    print(f"[4/4] 完成 {sz:.0f}MB, 总耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
