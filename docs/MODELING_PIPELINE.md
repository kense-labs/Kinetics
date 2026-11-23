# 工业模型生产管线手册（随工作台分发）

本工作台内置三条**设备模型生产管线**，收到的伙伴无需任何美术建模即可量产孪生装备。
所有产物落在 `frontend/public/twin-assets/`，`npm run build` 后入库即用。

## 路线 A：真机 STEP 装配体直转（最快，保真最高）

适用：厂商官网 / GrabCAD / 开源硬件仓库下载的装配体 STEP。

```bash
python3 -m venv .venv-cad && .venv-cad/bin/pip install -r tools/requirements-cad.txt
.venv-cad/bin/python tools/step_to_glb.py <输入.step> frontend/public/twin-assets/<装备id>.glb
npx gltfpack -i <装备id>.glb -o <装备id>.glb -c -kn -km -vpf   # 压缩(浮点位置保精度)
```

- 装配树零件名/层级/颜色自动保留 → **入库即带点选拆解 + 部件名牌**
- 撞名自动唯一化；`DROP_DIAG=<mm>` 环境变量过滤垫圈级微件（默认 4mm）
- `TOL`/`ANGTOL` 控制网格密度（默认 0.25mm/0.4rad，网页尺度足够）
- 顶层模块（装配树第一层）在 `equipment.js` 的 `partGroups` 里登记即成"总成"
- ⚠️ GLTFLoader 会把节点名空格转下划线：`partGroups` 键名要用清洗后名
- ⚠️ 许可：第三方 CAD 进库前在 `THIRD_PARTY_NOTICES.md` 登记来源与许可

实证：Voron 2.4 整机 241MB STEP → 9.2MB GLB，7,433 零件九大总成可拆。

## 路线 B：参数化装配体自生（无现成模型时）

适用：减速器/夹爪/输送模组等标准机理装备。模板：`tools/make_planetary_gearbox.py`
（行星减速器全参数：模数/齿数/齿比联动都是活的）。改参数即变机型；双导出 GLB+STEP，
STEP 可再走路线 A 回读验证无损。

## 路线 C：Blender 构件库组装（整机/场景级）

适用：岸桥/风机/分拣线/整厂合成。构件库在 `tools/blender_assets.py`
（桁架臂/三折返斜梯/电缆卷盘/拖令/光幕/警示纹/法兰螺栓圈……全参数化）：

```bash
Blender -b --python tools/blender_assets.py -- <装备id>   # 单件重建
Blender -b --python tools/compose_factory.py              # 整厂合成
bash tools/compress_assets.sh                              # 批量压缩(已压缩自动跳过)
```

## 出库验收（每台必过）

1. 正常视角截图：构图合理、无黑屏、无出画
2. 动画相位扫描：运动件方向正确、行程不穿模（行程表先行，穿模按构造排除）
3. 爆炸图：部件散开可读、名牌引线齐全、清单中文名+注解卡就位
4. 全家福重拼：`python3 tools/make_contact_sheet.py`（瓷砖持久化在 results/tiles/）
