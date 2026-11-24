// 设备建模: 嵌入实验台视口的设备精模展示 + 点击拆解(爆炸图) + 部件清单
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { createIcons, X, ScanLine, Layers, MousePointerClick, ArrowLeft, Play, Workflow, SlidersHorizontal } from "lucide";
import { TwinStage } from "./stage.js";
import { loadRobot } from "./robots.js";

const BUILDERS = {};
import { label as makeLabel, ground, studioStage, frameCamera, PALETTE } from "./kit.js";
import { EQUIPMENT_GROUPS, EQUIPMENT } from "./equipment.js";
import "./twin.css";

const TWIN_ICONS = { X, ScanLine, Layers, MousePointerClick, ArrowLeft, Play, Workflow, SlidersHorizontal };

const loader = new GLTFLoader();
loader.setMeshoptDecoder(MeshoptDecoder);   // twin-assets 全部 meshopt 压缩(-c -kn, 体积 ~1/5)
const loadCache = new Map();
function loadModel(file) {
  if (!loadCache.has(file))
    loadCache.set(file, new Promise((res, rej) =>
      // 保留 animations: 骨骼动画(UniMate 导出/任何绑定角色)由 AnimationMixer 播放
      // GLB 资产随构建可能同名替换(参数化→真 CAD), 浏览器 HTTP 缓存会拿旧文件 —— 加时间戳破缓存
      loader.load(`/twin-assets/${file}.glb?v=${Date.now()}`,
        (g) => res({ scene: g.scene, animations: g.animations ?? [] }), undefined, rej)));
  return loadCache.get(file);
}

// 深度释放: 几何/材质/贴图按引用去重后统一 dispose(场景切换不泄 GPU 资源)
function disposeDeep(root) {
  const geos = new Set(), mats = new Set(), texs = new Set();
  root.traverse((o) => {
    if (o.geometry) geos.add(o.geometry);
    for (const m of (Array.isArray(o.material) ? o.material : [o.material]).filter(Boolean)) {
      mats.add(m);
      for (const k of Object.keys(m)) { const v = m[k]; if (v?.isTexture) texs.add(v); }
      if (m.uniforms) for (const u of Object.values(m.uniforms)) { if (u?.value?.isTexture) texs.add(u.value); }
    }
  });
  for (const t of texs) t.dispose();
  for (const m of mats) m.dispose();
  for (const g of geos) g.dispose();
}

// 部件功能注解(名牌中文名 → 一句话功能): 点清单部件弹出功能卡; 只写功能事实, 不写无法核实的指标
const PART_NOTES = {
  // 岸桥
  "吊具": "集装箱专用吊具，扭锁锁箱后随小车沿大梁水平移动",
  "小车": "牵引式起重小车，沿大梁轨道往返，起升绞车随动",
  "大梁": "前大梁承载小车与吊载，A 字架拉杆平衡弯矩",
  "前拉杆": "A 字架拉杆组，承担前大梁外伸段载荷",
  "后拉杆": "A 字架拉杆组，与前拉杆对拉形成稳定三角",
  "机房": "起升与小车绞车、电控柜所在舱段",
  "小车轨道": "大梁顶部走行轨道，小车定位基准",
  "钢丝绳": "起升钢丝绳组，随吊具升降同步收放",
  "座舱": "司机室随小车移动，视野始终跟箱",
  "集装箱": "20ft 标准箱，装卸循环演示载荷",
  "门腿": "门框式支腿，整机沿码头轨道行走",
  "登机斜梯": "三折返登机斜梯，通机房层检修平台",
  "电缆卷盘": "高压电缆卷盘，大车走行时同步收放",
  // 风机
  "塔筒下段": "锥形钢塔筒下段，承载整机弯矩",
  "塔筒上段": "锥形钢塔筒上段，顶部接机舱",
  "机舱": "发电机与主传动链所在舱体",
  "轮毂": "三叶片变桨轮毂，风轮扭矩输入端",
  "轮毂罩": "轮毂整流罩，保护变桨机构",
  "警示灯": "航空障碍警示灯",
  // 堆垛机
  "左立柱": "双立柱门架之一，载货台升降导轨",
  "右立柱": "双立柱门架之一，载货台升降导轨",
  "载货台": "载货升降平台，货叉伸缩取放托盘",
  "左货叉": "伸缩货叉左臂，伸入货架取货",
  "右货叉": "伸缩货叉右臂，伸入货架取货",
  "拖链": "随载货台升降的供电/信号拖链",
  "行走台车": "巷道内水平行走台车，轮下即轨道",
  "操作面板": "立式操作面板，含触摸屏与急停按钮",
  "顶部横梁": "双立柱顶部刚性连接，保证门架刚度",
  // 无人集卡
  "底盘": "纯电驱动底盘，转向/驱动集成",
  "传感舱": "无驾驶室设计的传感器集成舱",
  "激光雷达": "主激光雷达，港区导航定位",
  "载货平板": "集装箱平板，四角扭锁固定",
  "前灯带": "前部状态示宽灯带",
  "尾灯带": "尾部状态示宽灯带",
  "左电池仓": "侧挂可换电电池仓",
  "右电池仓": "侧挂可换电电池仓",
  // iiwa / 机械臂通用
  "底座": "安装底座，含控制线缆入口",
  "肩部": "J2 肩部俯仰关节所在连杆",
  "大臂": "主承力连杆，决定臂展",
  "肘部": "J3/J4 肘部关节，冗余度来源",
  "小臂": "连接肘部与腕部的轻质连杆",
  "腕部": "腕关节组，末端姿态调整",
  "法兰盘": "末端法兰，ISO 工具接口",
  "左夹爪": "平行夹爪左指，伺服驱动",
  "右夹爪": "平行夹爪右指，伺服驱动",
  "线缆管": "关节内置线缆通道",
  "安装台座": "设备固定台座",
  // 叉车
  "车身": "平衡重式车身，含驱动与配重",
  "门架": "二级门架，货叉升降导轨",
  "货叉": "L 型货叉，叉取托盘载荷",
  "护顶架": "司机护顶架，防落物结构",
  // 塔吊
  "塔身": "标准节叠装塔身，承载回转上部",
  "起重臂": "变幅小车沿臂走行的工作臂",
  "平衡臂": "配重平衡臂，平衡起重臂弯矩",
  "回转平台": "上部回转平台，含回转支承",
  "吊钩组": "滑轮组吊钩，倍率变换起升",
  // 分拣线
  "线体机架": "模块化铝型材机架，辊筒安装基准",
  "辊筒组": "动力辊筒组，包裹输送执行面",
  "扫描门架": "视觉/光幕扫描门架，过件即识别",
  "分拣拨杆": "摆臂式分拣机构，把包裹拨入滑道",
  "分流滑道": "分拣下线滑道，接 rejected/分流件",
  "控制柜": "线体 PLC 与驱动控制柜",
  "警示灯柱": "三色状态灯柱：绿运行/黄分流/红异常",
  "红灯": "异常报警指示",
  "黄灯": "分流动作指示",
  "绿灯": "正常运行指示",
  // Voron 2.4 整机工程 STEP 九大总成注解
  "龙门架总成": "CoreXY 飞行龙门：双电机同步带传动 + 精密线轨 + 打印喷头总成",
  "Z 轴总成": "四丝杠独立驱动 Z 轴：支持四点调平 (Quad Gantry Leveling)",
  "电子仓": "底部电气中枢：主控板、步进驱动器与工业开关电源",
  "裙板": "底周蜂窝散热裙板：保护电子仓并形成风道",
  "框架": "2020 工业铝型材盲孔框架：整机高刚性承力骨架",
  "热床组件": "厚铸铝热床基板 + 双面 PEI 磁吸弹簧钢板",
  "封箱面板": "亚克力透明恒温封箱门板与后背吸音隔热板",
  "料架": "侧挂工程耗材料盘支座与 PTFE 导向管",
  "排气过滤总成": "舱内活性炭内循环与尾部排气过滤模组",
};

// 部件名美化(CAD 节点名 → 中文)
const PART_NAMES = {
  base: "底座", base_ring: "底座装饰环", turret: "回转座", shoulder: "肩部",
  upper_arm: "大臂", elbow: "肘部", forearm: "小臂", wrist: "腕部", flange: "法兰盘",
  jaw_l: "左夹爪", jaw_r: "右夹爪", cable: "线缆管", j1: "J1 回转关节", j2: "J2 肩俯仰关节",
  j3: "J3 肘俯仰关节", j4: "J4 腕关节", j2_ring: "J2 关节环", j3_ring: "J3 关节环",
  frame: "线体机架", rollers: "辊筒组", arch: "扫描门架", diverter_arm: "分拣拨杆",
  chute: "分流滑道", cabinet: "控制柜", tower: "警示灯柱",
  lamp_r: "红灯", lamp_y: "黄灯", lamp_g: "绿灯",
  body: "车体总成", mast: "液压门架", guard: "护顶架", beacon: "警示灯",
  // Voron 2.4 整机总成(STEP 装配树保真; GLTFLoader 会把空格转为下划线)
  Gantry: "龙门架总成", Z_Assembly: "Z 轴总成", Electronics: "电子仓", Skirt: "裙板",
  Frame: "框架", Bed_Components: "热床组件", Panels: "封箱面板", Spool_Holder: "料架",
  Exhaust_Filter_Assembly: "排气过滤总成",
};
function prettyPartName(raw) {
  if (PART_NAMES[raw]) return PART_NAMES[raw];
  // 机械臂连杆(Menagerie 命名)
  if (/^base/.test(raw)) return "基座";
  if (/^shoulder/.test(raw)) return "肩部连杆";
  if (/^upper_arm/.test(raw) || /^upperarm/.test(raw)) return "大臂";
  if (/^forearm/.test(raw)) return "小臂";
  if (/^half_arm_1/.test(raw)) return "小臂前段";
  if (/^half_arm_2/.test(raw)) return "小臂后段";
  if (/^spherical_wrist_1/.test(raw)) return "球腕一节";
  if (/^spherical_wrist_2/.test(raw)) return "球腕二节";
  if (/^bracelet/.test(raw)) return "视觉腕带模组";
  if (/^wrist_?1/.test(raw)) return "腕部一轴";
  if (/^wrist_?2/.test(raw)) return "腕部二轴";
  if (/^wrist_?3/.test(raw)) return "腕部三轴";
  if (/^hand/.test(raw)) return "手部";
  if (/gripper_base/.test(raw)) return "夹爪基座";
  if (/^left_finger/.test(raw)) return "左指";
  if (/^left_inner/.test(raw)) return "左内指节";
  if (/^left_outer/.test(raw)) return "左外指节";
  if (/^right_finger/.test(raw)) return "右指";
  if (/^right_inner/.test(raw)) return "右内指节";
  if (/^right_outer/.test(raw)) return "右外指节";
  if (/^end_tool/.test(raw)) return "末端法兰";
  if (/^link_base/.test(raw)) return "基座";
  if (/^link\d/.test(raw)) return `连杆 ${raw.slice(4)}`;
  if (/^pedestal/.test(raw)) return "安装台座";
  if (/^body/.test(raw)) return "车体";
  if (/^beacon/.test(raw)) return "警示灯";
  if (/^fork$/.test(raw)) return "货叉架";
  if (/^pallet/.test(raw)) return "托盘";
  if (/^payload/.test(raw)) return "载荷";
  if (/^w\d+$/.test(raw)) return "车轮";
  if (/^leg/.test(raw)) return "门腿";
  if (/^beam/.test(raw)) return "门架横梁";
  if (/^xbrace/.test(raw)) return "X 型斜撑";
  if (/^sill/.test(raw)) return "底横梁";
  if (/^tie/.test(raw)) return "拉杆";
  if (/^frame/.test(raw)) return "A 字架";
  if (/^blade/.test(raw)) return "叶片";
  if (/^mast/.test(raw)) return "立柱";
  if (/^wheel/.test(raw)) return "行走轮";
  if (/^rope/.test(raw)) return "钢丝绳";
  if (/^diverter/.test(raw)) return "分拣拨杆";
  if (/^conveyor/.test(raw)) return "输送线体";
  if (/^Cone/.test(raw)) return "塔筒";
  return raw;
}

// ---------- 设备动画驱动( exploded 时暂停, 包裹在爆炸时隐藏 ) ----------
// 关节轴一律按"期望的世界轴"反解到节点局部坐标, 不猜 GLB 轴向
function jointAxis(node, worldAxis) {
  const q = node.getWorldQuaternion(new THREE.Quaternion()).invert();
  return worldAxis.clone().applyQuaternion(q).normalize();
}

function cloneEmissiveMats(node, filter = null) {
  const mats = [];
  node?.traverse((c) => {
    if (!c.isMesh || !c.material) return;
    c.material = c.material.clone();
    if (!filter || filter(c.material)) mats.push(c.material);
  });
  return mats;
}

const ANIMS = {
  // Voron 2.4r2 (7,433 零件官方 STEP 装配体): 透明聚碳酸酯门板还原 + CoreXY 飞行龙门/X横梁/喷头三轴闭环驱动
  voron_printer(model) {
    // 还原官方 STEP 装配树中的 Transparent_Panels 为真实烟色透明亚克力门窗, 透视内部 7433 件精密机构
    const transGrp = model.getObjectByName("Transparent_Panels") || model.getObjectByName("Transparent Panels");
    transGrp?.traverse((c) => {
      if (c.isMesh && c.material) {
        c.material = c.material.clone();
        c.material.transparent = true;
        c.material.opacity = 0.22;
        c.material.roughness = 0.08;
        c.material.metalness = 0.12;
        c.material.depthWrite = false;
      }
    });
    const gantry = model.getObjectByName("Gantry");
    const xAxis = model.getObjectByName("X_Axis") || model.getObjectByName("X Axis");
    const xCarr = model.getObjectByName("X_Carriage") || model.getObjectByName("X Carriage");
    if (!gantry) return null;
    const gZ0 = gantry.position.z;
    const xY0 = xAxis ? xAxis.position.y : 0;
    const cX0 = xCarr ? xCarr.position.x : 0;
    let t0 = null, curZ = 45, curX = 0, curY = 0;
    const run = (dt, t, act = null) => {
      if (t0 === null) t0 = t;
      const tgtZ = act ? (act.gantry_z_mm ?? 45) : 55 + (Math.sin(t * 0.35) * 0.5 + 0.5) * 95;
      const tgtX = act ? (act.tool_x_mm ?? 0) + (act.printing ? Math.sin(t * 4.2) * 38 : 0) : Math.sin(t * 1.8) * 65;
      const tgtY = act ? (act.tool_y_mm ?? 0) + (act.printing ? Math.cos(t * 3.1) * 38 : 0) : Math.cos(t * 1.3) * 65;
      curZ += (tgtZ - curZ) * Math.min(1, dt * 4.5);
      curX += (tgtX - curX) * Math.min(1, dt * 6.0);
      curY += (tgtY - curY) * Math.min(1, dt * 6.0);
      gantry.position.z = gZ0 + (curZ - 45);
      if (xAxis) xAxis.position.y = xY0 + curY;
      if (xCarr) xCarr.position.x = cX0 + curX;
      run.task.count = Math.floor(((t - t0) * 0.35) / (Math.PI * 2));
    };
    run.task = { count: 0 };
    return run;
  },
  // KUKA iiwa 七轴精密装配单元: 支持后端关节目标(joints_rad / jaw_open_m) + TCP 荧光轨迹带
  robot_cell(model) {
    const j1 = model.getObjectByName("j1"), j2 = model.getObjectByName("j2"),
      j3 = model.getObjectByName("j3");
    const jl = model.getObjectByName("jaw_l"), jr = model.getObjectByName("jaw_r");
    if (!j2) return null;
    const h1 = j1?.quaternion.clone(), h2 = j2.quaternion.clone(), h3 = j3?.quaternion.clone();
    const a1 = j1 && jointAxis(j1, new THREE.Vector3(0, 1, 0));
    const a2 = jointAxis(j2, new THREE.Vector3(0, 0, 1));
    const a3 = j3 && jointAxis(j3, new THREE.Vector3(0, 0, 1));
    const j5 = model.getObjectByName("j5"), j7 = model.getObjectByName("j7");
    const h5 = j5?.quaternion.clone(), h7 = j7?.quaternion.clone();
    const zHinge = new THREE.Vector3(0, 0, 1);
    const trailSrc = model.getObjectByName("end_tool") ?? j7;
    const TRAIL_N = 260;
    const trailGeo = new THREE.BufferGeometry();
    const tPos = new Float32Array(TRAIL_N * 3), tCol = new Float32Array(TRAIL_N * 3);
    trailGeo.setAttribute("position", new THREE.BufferAttribute(tPos, 3));
    trailGeo.setAttribute("color", new THREE.BufferAttribute(tCol, 3));
    const trail = new THREE.Line(trailGeo,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95 }));
    trail.frustumCulled = false;
    trail.renderOrder = 5;
    trail.userData.twinAux = true;
    model.add(trail);
    const trailBeads = new THREE.Points(trailGeo,
      new THREE.PointsMaterial({ size: 0.032, vertexColors: true, transparent: true, opacity: 0.95, sizeAttenuation: true, depthWrite: false }));
    trailBeads.frustumCulled = false;
    trailBeads.renderOrder = 5;
    trailBeads.userData.twinAux = true;
    model.add(trailBeads);
    const tPts = [];
    const tw = new THREE.Vector3();
    let lastTcpW = null;
    const pq = (jl?.parent ?? j2).getWorldQuaternion(new THREE.Quaternion()).invert();
    const jdir = new THREE.Vector3(1, 0, 0).applyQuaternion(pq).normalize();
    const hlx = jl?.position.clone(), hrx = jr?.position.clone();
    const q = new THREE.Quaternion();
    let t0 = null, curJ = [0, 0, 0, 0, 0], curJaw = 0.014;
    const run = (dt, t, act = null) => {
      if (t0 === null) t0 = t;
      const jrads = act?.joints_rad;
      const targets = jrads
        ? [jrads[0] ?? 0, (jrads[1] ?? 0) * 0.8, (jrads[3] ?? 0) * 0.25, (jrads[5] ?? 0) * 0.4, jrads[6] ?? 0]
        : [Math.sin(t * 0.22) * 0.45, Math.sin(t * 0.5) * 0.22, Math.sin(t * 0.5 + 1.1) * 0.3, Math.sin(t * 0.4 + 0.7) * 0.3, Math.sin(t * 0.55 + 1.9) * 0.45];
      for (let i = 0; i < 5; i++) curJ[i] += (targets[i] - curJ[i]) * Math.min(1, dt * 5.5);
      if (j1) j1.quaternion.copy(h1).multiply(q.setFromAxisAngle(a1, curJ[0]));
      j2.quaternion.copy(h2).multiply(q.setFromAxisAngle(a2, curJ[1]));
      if (j3) j3.quaternion.copy(h3).multiply(q.setFromAxisAngle(a3, curJ[2]));
      if (j5) j5.quaternion.copy(h5).multiply(q.setFromAxisAngle(zHinge, curJ[3]));
      if (j7) j7.quaternion.copy(h7).multiply(q.setFromAxisAngle(zHinge, curJ[4]));
      if (trailSrc && dt > 0) {
        if (!trail.visible) { trail.visible = true; trailBeads.visible = true; }
        trailSrc.getWorldPosition(tw);
        const jumped = lastTcpW && tw.distanceTo(lastTcpW) > 0.45;
        if (jumped) tPts.length = 0;
        if (lastTcpW && !jumped) {
          const gap = tw.distanceTo(lastTcpW);
          for (let s = 1; s * 0.03 < gap && s < 40; s++)
            tPts.push(model.worldToLocal(lastTcpW.clone().lerp(tw, (s * 0.03) / gap)));
        }
        lastTcpW = (lastTcpW ?? new THREE.Vector3()).copy(tw);
        tPts.push(model.worldToLocal(tw.clone()));
        while (tPts.length > TRAIL_N) tPts.shift();
        const m = tPts.length;
        for (let i = 0; i < TRAIL_N; i++) {
          const src = tPts[Math.min(i, m - 1)] ?? tPts[0] ?? tw;
          tPos[i * 3] = src.x; tPos[i * 3 + 1] = src.y; tPos[i * 3 + 2] = src.z;
          const f = m > 1 ? Math.pow(i / (TRAIL_N - 1), 2) : 1;
          tCol[i * 3] = 0.02 + 0.2 * f; tCol[i * 3 + 1] = 0.18 + 2.0 * f; tCol[i * 3 + 2] = 0.15 + 1.65 * f;
        }
        trailGeo.attributes.position.needsUpdate = true;
        trailGeo.attributes.color.needsUpdate = true;
      }
      const tgtJaw = act ? (act.jaw_open_m ?? 0.014) : 0.014 * (Math.sin(t * 0.9) * 0.5 + 0.5);
      curJaw += (tgtJaw - curJaw) * Math.min(1, dt * 7);
      if (jl) jl.position.copy(hlx).addScaledVector(jdir, curJaw);
      if (jr) jr.position.copy(hrx).addScaledVector(jdir, -curJaw);
      run.task.count = Math.floor(((t - t0) * 0.5) / (Math.PI * 2));
    };
    run.onExploded = () => { trail.visible = false; trailBeads.visible = false; };
    run.task = { count: 0 };
    return run;
  },
  // KUKA KR210: 支持后端六轴关节指令(joints_rad)与演示轮播
  kr210(model) {
    const names = ["j1", "j2", "j3", "j4", "j5", "j6"];
    const J = {};
    for (const n of names) J[n] = model.getObjectByName(n);
    if (!J.j2) return null;
    const H = {}, A = {};
    const grab = (j, w) => { if (j) { H[j.name] = j.quaternion.clone(); A[j.name] = jointAxis(j, w); } };
    grab(J.j1, new THREE.Vector3(0, 1, 0));
    grab(J.j2, new THREE.Vector3(0, 0, 1));
    grab(J.j3, new THREE.Vector3(0, 0, 1));
    grab(J.j4, new THREE.Vector3(1, 0, 0));
    grab(J.j5, new THREE.Vector3(0, 0, 1));
    grab(J.j6, new THREE.Vector3(1, 0, 0));
    const q = new THREE.Quaternion();
    let t0 = null, cur = [0, 0, 0, 0, 0, 0];
    const run = (dt, t, act = null) => {
      if (t0 === null) t0 = t;
      const tgt = act?.joints_rad ?? [
        Math.sin(t * 0.22) * 0.5,
        Math.sin(t * 0.5) * 0.22,
        Math.sin(t * 0.5 + 1.1) * 0.3,
        Math.sin(t * 0.4 + 0.7) * 0.35,
        Math.sin(t * 0.55 + 1.9) * 0.28,
        Math.sin(t * 0.62 + 0.4) * 0.5,
      ];
      names.forEach((nm, idx) => {
        cur[idx] += ((tgt[idx] ?? 0) - cur[idx]) * Math.min(1, dt * 5.5);
        if (J[nm]) J[nm].quaternion.copy(H[nm]).multiply(q.setFromAxisAngle(A[nm], cur[idx]));
      });
      run.task.count = Math.floor(((t - t0) * 0.5) / (Math.PI * 2));
    };
    run.task = { count: 0 };
    return run;
  },
  // 叉车: 支持后端门架升降与底盘走行(fork_lift / chassis_z / pallet_loaded)
  forklift(model) {
    const fork = model.getObjectByName("fork");
    if (!fork) return null;
    const payloadNode = model.getObjectByName("payload");
    const riders = ["pallet", "payload"].map((n) => model.getObjectByName(n)).filter(Boolean);
    const beaconMats = cloneEmissiveMats(model.getObjectByName("beacon"));
    const fy = fork.position.y;
    const fq = fork.quaternion.clone();
    const fax = jointAxis(fork, new THREE.Vector3(1, 0, 0));
    const q2 = new THREE.Quaternion();
    const forkHome = fork.position.clone();
    const riderHome = riders.map((r) => ({ r, p: r.position.clone(), q: r.quaternion.clone() }));
    const homeZ = model.position.z;
    const s = { shuttle: 0, dir: 1, lift: 0.06 };
    let t0 = null;
    const run = (dt, t, act = null) => {
      if (t0 === null) t0 = t;
      if (act) {
        s.lift += ((act.fork_lift ?? 0.06) - s.lift) * Math.min(1, dt * 5);
        s.shuttle += ((act.chassis_z ?? 0) - s.shuttle) * Math.min(1, dt * 4);
        if (payloadNode) payloadNode.visible = act.pallet_loaded !== false;
      } else {
        s.lift = (Math.sin(t * 0.45) * 0.5 + 0.5) * 1.15;
        if (s.lift < 0.18) {
          s.shuttle += dt * 0.3 * s.dir;
          if (s.shuttle > 0.55) s.dir = -1;
          if (s.shuttle < -0.55) s.dir = 1;
        }
        if (payloadNode) payloadNode.visible = true;
      }
      const tiltQ = q2.setFromAxisAngle(fax, -s.lift * 0.045);
      fork.position.y = fy + s.lift;
      fork.quaternion.copy(fq).multiply(tiltQ);
      for (const rh of riderHome) {
        rh.r.position.copy(forkHome).add(new THREE.Vector3(0, s.lift, 0))
          .add(rh.p.clone().sub(forkHome).applyQuaternion(tiltQ));
        rh.r.quaternion.copy(tiltQ).multiply(rh.q);
      }
      model.position.z = homeZ + s.shuttle;
      const driving = s.lift < 0.18;
      for (const m of beaconMats) m.emissiveIntensity = driving ? 2.6 + Math.sin(t * 10) * 1.6 : 0.6;
      run.task.count = Math.floor(((t - t0) * 0.45) / (Math.PI * 2));
    };
    run.task = { count: 0 };
    return run;
  },
  // 分拣流水线: 支持后端视觉扫描与摆臂分拣决策(diverter_rad / parcel_x / parcel_z / scanning)
  sorting_line(model) {
    const pkgs = ["pkg1", "pkg2", "pkg3", "pkg4"].map((n) => model.getObjectByName(n)).filter(Boolean);
    const div = model.getObjectByName("diverter");
    const scanMats = [];
    model.getObjectByName("arch")?.traverse((c) => {
      if (c.isMesh && /cyan/.test(c.material?.name ?? "")) { c.material = c.material.clone(); scanMats.push(c.material); }
    });
    const lampMats = {
      r: cloneEmissiveMats(model.getObjectByName("lamp_r")),
      y: cloneEmissiveMats(model.getObjectByName("lamp_y")),
      g: cloneEmissiveMats(model.getObjectByName("lamp_g")),
    };
    if (!pkgs.length) return null;
    const homeZ = pkgs[0].position.z;
    const st = pkgs.map((p, i) => ({ p, divert: i % 2 === 1, x: p.position.x, z: homeZ, homeY: p.position.y, out: 0 }));
    const SPAWN_X = -3.95, BELT_END = 3.55;
    const rollers = [];
    model.traverse((c) => { if (c.isMesh && /^_r\d/.test(c.name)) rollers.push(c); });
    const rax = rollers.length ? jointAxis(rollers[0], new THREE.Vector3(0, 0, 1)) : null;
    const sweep = new THREE.Mesh(
      new THREE.PlaneGeometry(0.02, 1.1),
      new THREE.MeshBasicMaterial({ color: 0x3cf0d0, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
    sweep.position.set(0.6, 1.25, 0);
    sweep.visible = false;
    sweep.userData.twinAux = true;
    model.add(sweep);
    let sweepT = 1;
    const divHome = div?.quaternion.clone();
    const divAx = div && jointAxis(div, new THREE.Vector3(0, 1, 0));
    const dq = new THREE.Quaternion();
    let divAng = 1.5, curPx = -2.2, curPz = 0;
    const run = (dt, t, act = null) => {
      if (rax) for (const r of rollers) r.rotateOnAxis(rax, -dt * 0.85 / 0.03);
      if (act) {
        const p0 = st[0];
        for (let i = 1; i < st.length; i++) st[i].p.visible = false;
        p0.p.visible = true;
        p0.p.scale.setScalar(1);
        curPx += ((act.parcel_x ?? -2.2) - curPx) * Math.min(1, dt * 5.5);
        curPz += ((act.parcel_z ?? 0) - curPz) * Math.min(1, dt * 5.5);
        const slide = Math.max(0, homeZ - curPz);
        p0.p.position.set(curPx, p0.homeY - slide * (0.05 / 0.98), curPz);
        const target = act.diverter_rad ?? 1.48;
        divAng += (target - divAng) * Math.min(1, dt * 7);
        if (div) div.quaternion.copy(divHome).multiply(dq.setFromAxisAngle(divAx, divAng));
        if (act.scanning && sweepT >= 1) sweepT = 0;
        sweepT = Math.min(1, sweepT + dt / 0.5);
        sweep.visible = sweepT < 1;
        if (sweep.visible) {
          sweep.position.z = -0.55 + sweepT * 1.1;
          sweep.material.opacity = Math.sin(sweepT * Math.PI) * 0.85;
        }
        for (const m of scanMats) m.emissiveIntensity = act.scanning ? 3.2 : 1.5;
        for (const m of lampMats.g) m.emissiveIntensity = act.chute_full ? 0.3 : 1.8;
        for (const m of lampMats.y) m.emissiveIntensity = act.diverting ? 2.6 + Math.sin(t * 8) * 0.8 : 0.25;
        for (const m of lampMats.r) m.emissiveIntensity = act.chute_full ? 2.8 : 0.25;
        return;
      }
      let diverting = false, scanning = false;
      for (const s of st) {
        s.p.visible = true;
        s.x += dt * 0.85;
        if (s.divert && s.x > 1.05 && s.x < 2.7) {
          s.z = Math.max(s.z - dt * 1.2, homeZ - 0.98);
          if (s.z > homeZ - 0.9) diverting = true;
        }
        const diverted = s.divert && s.z <= homeZ - 0.97;
        if (diverted) s.out += dt;
        const slide = homeZ - s.z;
        s.p.position.y = s.homeY - slide * (0.05 / 0.98);
        s.p.position.x = s.x;
        s.p.position.z = s.z;
        const fadeOut = diverted ? Math.min(1, s.out / 0.6)
                                 : THREE.MathUtils.smoothstep(s.x, BELT_END - 0.6, BELT_END);
        const fadeIn = THREE.MathUtils.smoothstep(s.x, SPAWN_X, SPAWN_X + 0.6);
        const k = Math.max(0.02, (1 - fadeOut) * fadeIn);
        s.p.scale.setScalar(k);
        s.p.visible = k > 0.045;
        s.p.position.y -= (1 - k) * (s.homeY - 0.769);
        if (Math.abs(s.x - 0.6) < 0.5 && s.z === homeZ) scanning = true;
        if (s.x > BELT_END || s.out >= 0.6) { s.x = SPAWN_X; s.z = homeZ; s.out = 0; run.task.count++; }
      }
      if (scanning && sweepT >= 1) sweepT = 0;
      sweepT = Math.min(1, sweepT + dt / 0.5);
      sweep.visible = sweepT < 1;
      if (sweep.visible) {
        sweep.position.z = -0.55 + sweepT * 1.1;
        sweep.material.opacity = Math.sin(sweepT * Math.PI) * 0.85;
      }
      const armNeeded = diverting || st.some((s) => s.divert && s.z === homeZ && s.x > 0.2 && s.x < 2.7);
      const target = armNeeded ? 0 : 1.5;
      divAng += (target - divAng) * Math.min(1, dt * 6);
      if (div) div.quaternion.copy(divHome).multiply(dq.setFromAxisAngle(divAx, divAng));
      for (const m of scanMats) m.emissiveIntensity = scanning ? 3.2 : 1.5;
      for (const m of lampMats.g) m.emissiveIntensity = 1.8;
      for (const m of lampMats.y) m.emissiveIntensity = diverting ? 2.6 + Math.sin(t * 8) * 0.8 : 0.25;
      for (const m of lampMats.r) m.emissiveIntensity = 0.25;
    };
    run.onExploded = () => { for (const s of st) s.p.visible = false; sweep.visible = false; };
    run.task = { count: 0 };
    return run;
  },
};

export function createTwin(container, opts = {}) {
  // 嵌入实验台视口: 深色影棚画布 + 可折叠右侧参数/部件抽屉 + 响应式操控坞
  container.innerHTML = `
  <div class="twin-shell embedded">
    <canvas id="twin-canvas"></canvas>
    <div class="twin-label"><h1 id="twin-title"></h1><p id="twin-subtitle"></p></div>
    <div class="twin-hud" id="twin-hud" hidden>
      <div class="hud-head"><span class="hud-metric"></span><span class="hud-row"><strong class="hud-count">0</strong><span class="hud-target"></span></span></div>
      <div class="hud-bar"><i></i></div>
    </div>
    <div class="twin-top-actions">
      <button class="twin-top-btn active" id="twin-side-toggle" type="button" aria-expanded="true" title="展开/收起参数与部件清单"><i data-lucide="sliders-horizontal"></i><span>参数与部件</span></button>
      <button class="twin-top-btn twin-back" id="twin-back" type="button"><i data-lucide="arrow-left"></i><span>返回仿真</span></button>
    </div>
    <div class="twin-side" id="twin-side">
      <section class="twin-side-sec"><h2 class="twin-h2">设备参数</h2>
        <p class="twin-goal" id="twin-goal"></p>
        <table class="twin-specs" id="twin-specs"></table></section>
      <section class="twin-side-sec twin-side-grow"><h2 class="twin-h2">部件清单<span class="twin-unit" id="twin-part-count"></span></h2>
        <ol class="twin-parts" id="twin-parts"></ol></section>
    </div>
    <div class="twin-hint">拖拽旋转 · 滚轮缩放 · 点击部件高亮</div>
    <div class="twin-dock">
      <button class="twin-explode-btn embed twin-line-btn" id="twin-line" type="button"><i data-lucide="workflow"></i><span>产线巡检</span></button>
      <button class="twin-explode-btn embed twin-tour-btn" id="twin-tour" type="button"><i data-lucide="play"></i><span>演示轮播</span></button>
      <button class="twin-explode-btn embed" id="twin-explode" type="button"><i data-lucide="layers"></i><span>拆解 / 装配</span></button>
    </div>
    <div class="twin-caption" id="twin-caption"></div>
    <div class="twin-flow" id="twin-flow" hidden>
      <span data-ch="0">来料</span><i>→</i><span data-ch="1">分拣</span><i>→</i><span data-ch="2">上下料</span><i>→</i><span data-ch="3">入库</span>
    </div>
    <div class="twin-pick" id="twin-pick" hidden></div>
    <div class="twin-fade" id="twin-fade"></div>
  </div>`;

  const $ = (s) => container.querySelector(s);
  const canvas = $("#twin-canvas");
  const stage = new TwinStage(canvas);
  // 视角完全手动(自动旋转会干扰点部件和细看)

  let current = null;      // { def, modelRoot, parts:[{node,name,home,center,dir}], exploded, labels }
  let explodeAnim = 0;     // 0..1 动画进度
  let explodeTarget = 0;
  let taskActive = true;   // 设备任务: 运行/暂停(默认进入即运行演示)
  let taskCountBase = 0;   // 重置偏移(计数器是单调的, 重置 = 记基线)
  let currentAnim = null;  // 当前设备动画 fn(带 task.count 单调计数)
  let shownCount = -1;
  let liveBackendSnap = null;  // 后端决策控制实时状态快照(/api/equipment/state)

  function applyBackendState(snap) {
    liveBackendSnap = snap || null;
    if (snap && current?.def?.id === snap.equipment_id) {
      taskActive = snap.status === "running";
      syncTaskCount();
    }
  }

  // 任务状态(计数为单调值; 显示值 = 计数 - 基线) —— 由实验台原生控件呈现(main.js 同步)
  let hudLast = -2;   // HUD 仅在数值变化时写 DOM
  function updateHud() {
    const el = $("#twin-hud"); if (!el) return;
    const task = current?.def?.task;
    if (!task) { el.hidden = true; return; }
    const c = Math.max(0, shownCount);
    const tgt = (liveBackendSnap?.equipment_id === current?.def?.id ? liveBackendSnap.observation?.target : null) ?? task.target;
    if (c === hudLast && el.dataset.taskName === `${task.name}:${tgt}`) return;
    hudLast = c; el.dataset.taskName = `${task.name}:${tgt}`;
    el.hidden = false;
    el.querySelector(".hud-metric").textContent = task.name;
    el.querySelector(".hud-count").textContent = c;
    el.querySelector(".hud-target").textContent = `/ ${tgt} ${task.unit}`;
    el.querySelector(".hud-bar i").style.width = `${Math.min(100, (c / tgt) * 100)}%`;
    const done = c >= tgt;
    if (done && !el.classList.contains("done")) { el.classList.add("done", "flash"); setTimeout(() => el.classList.remove("flash"), 1600); }
    if (!done) el.classList.remove("done", "flash");
  }
  function syncTaskCount() {
    const task = current?.def?.task;
    if (!task) { shownCount = 0; updateHud(); return; }
    if (!tourMode && liveBackendSnap?.equipment_id === current?.def?.id) {
      shownCount = liveBackendSnap.observation?.completed ?? 0;
      updateHud();
      return;
    }
    shownCount = Math.max(0, (currentAnim?.task?.count ?? 0) - taskCountBase);
    updateHud();
  }
  function taskToggle() {
    taskActive = !taskActive;
  }
  function taskReset() {
    taskCountBase = currentAnim?.task?.count ?? 0;
    shownCount = -1;
    syncTaskCount();
  }

  // 拆解标签(引线 + 名牌)
  function makePartLabel(text) {
    // 名牌世界尺寸随设备高度缩放: 26m 塔吊在 56m 机位下, 0.52 基准只有亚像素大
    const h = current?.def?.height ?? 2.2;
    const size = 0.52 * Math.min(8, Math.max(0.45, h / 2.2));
    const sp = makeLabel(text, size, "#bff3e6", "rgba(8,32,26,0.85)");
    return sp;
  }

  function buildParts(model, linkNodes = null, scale = 1, explodeK = 1) {
    const rootBb = new THREE.Box3().setFromObject(model);
    const rootC = rootBb.getCenter(new THREE.Vector3());
    // 机器人: 直接用连杆组; 装备: 叶级命名节点(GLTF 单材质→Mesh, 多材质→Group[Mesh...])
    let nodes;
    if (linkNodes && linkNodes.length) {
      nodes = linkNodes;
    } else {
      nodes = [];
      model.traverse((n) => {
        if (n === model) return;                     // 模型根节点永不当部件(否则整台只算一件)
        const nm = n.name ?? "";
        // 包裹是被分拣物; _前缀=内部细节(辊筒/皮带/图元); j\d=/iiwa_root=运动枢轴;
        // Blender 图元自动名(mesh_NN/Cube/Cylinder...)是材质拆件, 都不是部件
        if (!nm || /^pkg\d/.test(nm) || nm.startsWith("_")) return;
        if (/^j\d+$/.test(nm) || nm === "iiwa_root") return;
        if (/^(mesh_\d+|(Cube|Cylinder|Cone|Sphere|Plane|Circle|Icosphere|Monkey|Torus|BezierCurve|BezierCircle)(\.|_|\d|$))/i.test(nm)) return;
        // 有效载荷: 自身是网格/点云, 或子树含网格(点云)(gltfpack 会把网格挪到命名空节点的子级)
        const geomCarrier = (c) => { let f = (c.isMesh || c.isPoints) === true; if (!f) c.traverse((d) => { if (d.isMesh || d.isPoints) f = true; }); return f; };
        let carriesGeom = geomCarrier(n);
        if (!carriesGeom) return;
        // 程序化构建器的部件图钉: 部件边界由构建器显式声明, 直接当选不被父级归并吞掉
        if (n.userData?.partPin) { nodes.push(n); return; }
        // 父级是几何容器(多图元 Group)且不是模型根/运动枢轴 → 让父级当部件, 避免重复计数
        const p = n.parent;
        const isPivot = p && (/^j\d+$/.test(p.name ?? "") || p.name === "iiwa_root");
        if (p && p !== model && p.name && !isPivot && !p.userData?.partPin && p.children.length > 0 && p.children.every(geomCarrier)) return;
        nodes.push(n);
      });
      if (!nodes.length) nodes = model.children.filter((n) => n.isMesh);
    }
    const parts = [];
    // 先量中心再按高度排名: 爆炸 = 黄金角螺旋 + 纯向上竖直分层(不穿地台)
    const measured = [];
    for (const node of nodes) {
      const bb = new THREE.Box3().setFromObject(node);
      if (bb.isEmpty()) continue;
      measured.push({ node, center: bb.getCenter(new THREE.Vector3()) });
    }
    const ranked = [...measured].sort((a, b) => a.center.y - b.center.y);
    const rankOf = new Map(ranked.map((m, i) => [m.node, i]));
    const rootDiag = rootBb.getSize(new THREE.Vector3()).length();
    for (const m of measured) {
      const { node, center } = m;
      const parentQuat = new THREE.Quaternion();
      if (node.parent) node.parent.getWorldQuaternion(parentQuat);
      const inv = parentQuat.clone().invert();
      let off = null, dir, localDir = null;
      if (measured.length > 2) {
        // 黄金角螺旋 + 按高度纯向上分层 —— 机器人连杆与装备统一的爆炸散开
        const rk = rankOf.get(node);
        const u = rk / Math.max(1, measured.length - 1);
        const a = rk * 2.399963;
        // explodeK: 整厂机组级拆解用 0.32 收敛(机组本来就散开, 只需轻度分层抬起;
        // 全量公式是按单机密集部件调的, 直接套会把机组抛到几十米高空)
        const rf = (rootDiag * 0.10 * explodeK) / scale;
        const hh = (rootDiag * 0.62 * explodeK) / scale;
        off = new THREE.Vector3(Math.cos(a) * rf, u * hh, Math.sin(a) * rf).applyQuaternion(inv);
        dir = off.clone().normalize();
      } else {
        dir = center.clone().sub(rootC).normalize();
        localDir = dir.clone().applyQuaternion(inv);
      }
      parts.push({ node, name: prettyPartName(node.name || "部件"), home: node.position.clone(), center, worldDir: dir.clone(), dir: localDir, off });
    }
    return parts;
  }

  function applyExplode(k) {
    if (!current) return;
    for (const p of current.parts) {
      if (p.off) p.node.position.copy(p.home).addScaledVector(p.off, k);
      else p.node.position.copy(p.home).addScaledVector(p.dir, k * p.dist);
    }
  }

  function rebuildLabels() {
    if (!current) return;
    for (const lp of current.labels ?? []) { stage.scene.remove(lp.sprite); stage.scene.remove(lp.line); disposeDeep(lp.sprite); disposeDeep(lp.line); }
    current.labels = [];
    for (const p of current.parts) {
      const sprite = makePartLabel(p.name);
      const lineGeo = new THREE.BufferGeometry().setFromPoints([p.centerWorld, p.centerWorld.clone()]);
      const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: 0x10846a, transparent: true, opacity: 0 }));
      line.frustumCulled = false;   // 引线端点逐帧原地改写, 不做包围球剔除
      sprite.material.opacity = 0;
      stage.add(sprite); stage.add(line);
      current.labels.push({ sprite, line, part: p });
    }
  }

  function updateLabels() {
    if (!current) return;
    const k = explodeAnim;
    const n = current.parts.length;
    const R = current.labelRadius ?? 3;
    // 名牌按爆炸高度排序, 铺在朝向相机的 240° 弧带上 —— 不被模型遮挡且自然分层,
    // 杜绝黄金角满环布局在固定机位下的投影重叠(连杆5/连杆1 曾撞名)
    if (k > 0.95 && !current.labelRankLive) {
      // 爆炸完成后按部件**真实世界高度**重算榜单(估算的 distWorld 与实际层叠行程有差)
      const meas = current.parts.map((p) => {
        const b = new THREE.Box3().setFromObject(p.node);
        return { p, y: b.getCenter(new THREE.Vector3()).y };
      });
      meas.sort((a, b) => a.y - b.y);
      current.labelRank = new Map(meas.map((m, i) => [m.p, i]));
      current.labelY0 = meas[0].y;
      const m2l = Math.ceil(meas.length / 2);
      current.labelSpan = Math.max(0.6, meas[meas.length - 1].y - meas[0].y, m2l * 0.16);
      current.labelRankLive = true;
    } else if (!current.labelRank) {
      const sorted = [...current.parts].sort((a, b) => (a.center.y + a.distWorld) - (b.center.y + b.distWorld));
      current.labelRank = new Map(sorted.map((p, i) => [p, i]));
      const ys = sorted.map((p) => p.center.y + p.distWorld);
      current.labelY0 = Math.min(...ys);
      const m2 = Math.ceil(current.parts.length / 2);
      current.labelSpan = Math.max(0.6, Math.max(...ys) - current.labelY0, m2 * 0.16);
    }
    if (k > 0.02 && (current.labelAz === undefined || k < 0.95)) {
      const mc = new THREE.Box3().setFromObject(current.root).getCenter(new THREE.Vector3());
      current.labelAz = Math.atan2(stage.camera.position.x - mc.x, stage.camera.position.z - mc.z);
    }
    const COL = 1.02;   // 左右榜各在相机方位 ±58°
    const m2 = Math.ceil(n / 2);
    for (const lp of current.labels) {
      const p = lp.part;
      // 部件中心随拆解移动: 用节点当前世界包围盒中心
      const bb = new THREE.Box3().setFromObject(p.node);
      const c = bb.getCenter(new THREE.Vector3());
      const rank = current.labelRank.get(p) ?? 0;
      const col = rank < m2 ? 0 : 1;                    // 低半榜左, 高半榜右
      const j = col === 0 ? rank : rank - m2;
      const mc = col === 0 ? m2 : n - m2;
      const a = current.labelAz + (col === 0 ? -COL : COL);
      const ly = current.labelY0 + (mc > 1 ? (j / (mc - 1)) * current.labelSpan : current.labelSpan / 2);
      lp.sprite.position.set(c.x + Math.cos(a) * R * k, c.y * (1 - k) + ly * k, c.z + Math.sin(a) * R * k);
      lp.sprite.material.opacity = k;
      lp.line.material.opacity = k * 0.7;
      // 端点原地改写: setFromPoints 每帧新建 BufferAttribute, 旧 GPU 缓冲只能等 GC 回收(爆炸动画期间持续泄漏)
      const pa = lp.line.geometry.attributes.position;
      pa.setXYZ(0, c.x, c.y, c.z);
      pa.setXYZ(1, lp.sprite.position.x, lp.sprite.position.y, lp.sprite.position.z);
      pa.needsUpdate = true;
    }
  }

  let selectSeq = 0;   // 切换令牌: 晚到的异步加载结果直接丢弃

  // 构图并把主体向左让位, 躲开右侧参数/部件浮层
  let currentMarginOverride = null;
  let sideUserToggled = false;
  function setSideCollapsed(collapsed) {
    const side = $("#twin-side");
    const btn = $("#twin-side-toggle");
    if (!side || !btn) return;
    side.classList.toggle("collapsed", collapsed);
    btn.classList.toggle("active", !collapsed);
    btn.setAttribute("aria-expanded", String(!collapsed));
  }
  function composeFrame(bb) {
    const side = container.querySelector(".twin-side:not(.collapsed)");
    const vpW = container.clientWidth || 1;
    const frac = side ? (side.offsetWidth + 24) / vpW / 2 : 0;   // 主体中心移到剩余区中央
    // 左移会吃掉左侧画面空间, 构图距离同步放宽; 高瘦顶重设备用 def.margin 加余量防顶边亲吻
    frameCamera(stage, bb, 24, 36, 1.52 * (1 + frac * 0.85) * (currentMarginOverride ?? 1));
    if (frac > 0.02) {
      const cam = stage.camera;
      const fwd = stage.controls.target.clone().sub(cam.position).normalize();
      const right = fwd.clone().cross(cam.up).normalize();
      const shift = frac * 2 * cam.position.distanceTo(stage.controls.target)
        * Math.tan((cam.fov * Math.PI / 180) / 2) * cam.aspect;
      cam.position.addScaledVector(right, shift);
      stage.controls.target.addScaledVector(right, shift);
    }
  }

  function selectEquipment(id) {
    const seq = ++selectSeq;
    const def = EQUIPMENT.find((e) => e.id === id) ?? EQUIPMENT[0];
    currentMarginOverride = def.margin ?? null;   // 高瘦顶重设备的构图余量
    opts.onSceneChange?.(def, { tourMode });
    if (!sideUserToggled && container.clientWidth > 0) {
      setSideCollapsed(container.clientWidth < 680);
    }
    // 换机过场: 快入黑场遮罩(加载间隙/冷载解码都被盖住), 新机位就绪后缓出
    const fadeEl = $("#twin-fade");
    if (fadeEl) { fadeEl.classList.remove("out"); fadeEl.classList.add("on"); }
    // GPU 资源收尾(在 clearScene 之前): 名牌画布纹理 + 引线几何 + 影棚地台(全部 twin 自建件)
    for (const l of current?.labels ?? []) { disposeDeep(l.sprite); disposeDeep(l.line); }
    const oldAux = [];
    current?.root?.traverse((o) => { if (o.userData?.twinAux) oldAux.push(o); });
    for (const o of oldAux) { o.parent?.remove(o); disposeDeep(o); }
    if (current?.def?.build && current.root) disposeDeep(current.root);
    for (const c of [...stage.scene.children])
      if (c.userData?.twinOwned) { stage.scene.remove(c); disposeDeep(c); }
    stage.afterRender = null;
    current = null;
    stage.clearScene();
    container.querySelector(".twin-clip-chip")?.remove();   // 清掉上一台的动画剪辑 chip
    $("#twin-pick").hidden = true;
    $("#twin-title").textContent = def.name;
    $("#twin-subtitle").textContent = `设备建模 / ${def.id.toUpperCase()}`;
    $("#twin-goal").textContent = def.subtitle;
    $("#twin-specs").innerHTML = def.specs.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("");
    $("#twin-parts").innerHTML = '<li class="alert-empty">模型加载中…</li>';
    currentAnim = null;
    taskActive = true; taskCountBase = 0; shownCount = -1; hudLast = -2;   // 任务状态归零(呈现交给实验台控件)
    for (const b of container.querySelectorAll(".twin-nav-item"))
      b.classList.toggle("active", b.dataset.scene === def.id);

    stage.add(new THREE.Group(), explodeDriver);   // 在 clearScene 之后注册
    stage.add(new THREE.Group(), tourDriver);      // 轮播驱动同生命周期(切台重建)
    explodeAnim = 0; explodeTarget = 0;
    $("#twin-explode").classList.remove("active");   // 切设备后按钮态与爆炸态保持一致

    const promise = def.robot
      ? loadRobot(def.robot, def.pose || null)
      : def.build
        ? Promise.resolve(BUILDERS[def.build]())   // 程序化装备(点云/生成类, 无 GLB)
        : loadModel(def.file).then((src) => ({
          // 带动画的模型不克隆(骨骼/补偿缩放链在克隆下会断), 直接用源场景(本视图同时只有一台)
          group: src.animations.length ? src.scene : src.scene.clone(true),
          links: null, animations: src.animations,
        }));
    promise.then((payload) => {
      if (seq !== selectSeq) return;   // 加载途中用户已切换设备, 丢弃
      const model = payload.group;
      const robotLinks = payload.links;
      const bb = new THREE.Box3().setFromObject(model);
      const size = bb.getSize(new THREE.Vector3());
      const scale = def.height / (size.y || 1);
      model.scale.setScalar(scale);
      const bb2 = new THREE.Box3().setFromObject(model);
      const ctr = bb2.getCenter(new THREE.Vector3());
      model.position.set(-ctr.x, -bb2.min.y, -ctr.z);
      model.traverse((c) => {
        if (c.isMesh) {
          c.castShadow = true; c.receiveShadow = true;
          if (c.material?.emissive && c.material.emissiveIntensity > 1.8)
            c.material.emissiveIntensity = 1.5;   // 近距离防爆光
        }
      });
      const root = new THREE.Group();
      root.add(model);
      stage.add(root);
      // 影棚地台按设备**水平投影**定半径(高瘦设备按体对角线会把地台放大好几倍, 构图全空)
      const finalBb = new THREE.Box3().setFromObject(root);
      const fs = finalBb.getSize(new THREE.Vector3());
      const stageR = Math.max(2.4, Math.hypot(fs.x, fs.z) * 0.68 + 0.55);
      if (!def.noStage) {   // 整厂场景自带车间地坪/装修, 影棚地台+光环会压住厂区, 跳过
        const studio = studioStage(stageR);
        studio.userData.twinOwned = true;   // 切换设备时 dispose(画布纹理+几何不泄漏)
        stage.add(studio);
      } else if (def.apron !== false) {
        // 整厂无影棚: 代码铺深色裙地填满地平线以下的虚空。
        // 挂 stage 而非 root —— 不进 finalBb(爆炸分层/阴影视锥/名牌半径全按模型 bbox 算, 裙地不能撑大它)
        const apron = new THREE.Mesh(
          new THREE.CircleGeometry(120, 64),
          new THREE.MeshStandardMaterial({ color: 0x14171b, roughness: 0.95, metalness: 0.0 }));
        apron.rotation.x = -Math.PI / 2;
        apron.position.y = 0.005;   // 地坪底面 y=0, 略高于它避免 z-fight(重叠区被车间地坪盖住)
        apron.receiveShadow = true;
        apron.userData.twinOwned = true;
        stage.add(apron);
      }
      fit();   // 确保由隐藏态切入后 camera.aspect 与渲染尺寸先对齐, 再计算构图偏移
      composeFrame(finalBb);
      // 手工机位(def.manualFrame 显式开关, 高瘦顶重设备自动构图会切顶才用): camera=机位, camTarget=目标点
      if (def.manualFrame && def.camera) {
        stage.resetCamera(def.camera,
          def.camTarget ?? [ctr.x, Math.min(ctr.y, fs.y * 0.42), ctr.z]);
      }
      stage.fitShadow(finalBb);   // 阴影视锥贴合当前设备(毫米级 texel, 接触阴影锐利)
      // 新机位就绪: 过场遮罩缓出(快入的 .on 移除, 换成 240ms 缓出)
      if (fadeEl) requestAnimationFrame(() => { fadeEl.classList.add("out"); fadeEl.classList.remove("on"); });
      // 部件清单: def.partGroups(整厂机组级) > 机械臂连杆 > 叶级命名节点
      const groupNodes = def.partGroups?.map((n) => model.getObjectByName(n)).filter(Boolean);
      const useGroups = groupNodes?.length > 0;
      // def.explodeK: 场景级爆炸阻尼(整厂机组 0.32; 面板类 UI 场景 0.45 防薄片飞散)
      const parts = buildParts(model, useGroups ? groupNodes : robotLinks, scale, def.explodeK ?? (useGroups ? 0.32 : 1));
      for (const p of parts) {
        // buildParts 的包围盒在缩放后的模型上量取, 已是世界坐标, 不能再乘 scale
        p.centerWorld = p.center.clone();
        // 机械臂连杆散开会沿链叠加, 用更小的步距
        p.dist = robotLinks ? size.length() * 0.13
                            : (0.55 + (p.dir?.length() ?? 1) * 0.4) * size.length() * 0.26;
        p.distWorld = p.dist * scale;
      }
      parts.forEach((p, i) => { p.labelIdx = i; });
      // 同名多件自动编号(门腿/叶片/车轮等), 清单与名牌一一对应
      const nameCount = {};
      for (const p of parts) nameCount[p.name] = (nameCount[p.name] ?? 0) + 1;
      const nameSeen = {};
      for (const p of parts) if (nameCount[p.name] > 1) p.name = `${p.name} ${(nameSeen[p.name] = (nameSeen[p.name] ?? 0) + 1)}`;
      current = { def, root, parts, size: size.length() * scale, scale };
      syncTaskCount();   // HUD 立即就位(0/target), 不等第一帧动画
      current.maxDistWorld = Math.max(...parts.map((p) => (p.off ? p.off.length() * scale : p.distWorld)), 0.5);
      current.labelRadius = Math.max(current.maxDistWorld * 0.55, current.size * 0.45) + current.size * 0.15;
      rebuildLabels();
      // 动画辅助件(轨迹带/钢丝绳/吊钩组/光幕)挂在缓存模型上, 每次建台都会新建:
      // 先清掉上次残留的副本 —— 防几何累积泄显存, 也防同位双份 Z-fighting
      const staleAux = [];
      model.traverse((o) => { if (o.userData?.twinAux) staleAux.push(o); });
      for (const o of staleAux) { o.parent?.remove(o); disposeDeep(o); }
      // 设备动画驱动(爆炸态暂停; 注册在 clearScene 之后; 任务计数同步到任务卡)
      const anim = ANIMS[def.id]?.(model);
      if (anim) {
        anim.task ??= { count: 0 };
        currentAnim = anim;
        stage.add(new THREE.Group(), (dt, t) => {
          if (explodeAnim >= 0.02) { anim.onExploded?.(); return; }
          const liveAct = (!tourMode && liveBackendSnap?.equipment_id === def.id)
            ? (liveBackendSnap.observation?.actuators ?? null)
            : null;
          if (liveAct) {
            if (!liveBackendSnap.observation?.estop) anim(dt, t, liveAct);
            syncTaskCount();
            return;
          }
          if (!taskActive) return;                      // 任务暂停 = 机构停摆
          anim(dt, t, null);
          syncTaskCount();
        });
      }
      // 骨骼动画桥: GLB 自带剪辑(UniMate/绑定角色导出) → AnimationMixer + 剪辑切换 chip
      if (payload.animations?.length) {
        const mixer = new THREE.AnimationMixer(model);
        const actions = payload.animations.map((c) => mixer.clipAction(c));
        let clipIdx = 0;
        actions[0].play();
        stage.add(new THREE.Group(), (dt) => { if (explodeAnim < 0.02) mixer.update(dt); });
        const chip = document.createElement("button");
        chip.className = "twin-clip-chip";
        chip.type = "button";
        const setChip = () => {
          chip.innerHTML = `<i data-lucide="play"></i><span>动画 ${payload.animations[clipIdx].name || clipIdx + 1} · ${clipIdx + 1}/${payload.animations.length}</span>`;
          createIcons({ icons: TWIN_ICONS, root: chip });
        };
        setChip();
        chip.onclick = () => {
          actions[clipIdx].fadeOut(0.2);
          clipIdx = (clipIdx + 1) % actions.length;
          actions[clipIdx].reset().fadeIn(0.2).play();
          setChip();
        };
        container.querySelector(".twin-shell").append(chip);
      }
      $("#twin-part-count").textContent = `${parts.length} 件`;
      $("#twin-parts").innerHTML = parts.map((p, i) =>
        `<li data-part="${i}"><i data-lucide="mouse-pointer-click"></i><b>${p.name}</b></li>`).join("");
      createIcons({ icons: TWIN_ICONS, root: $("#twin-parts") });
    }).catch((err) => {
      console.error("equipment load/build failed", err);
      window.__loadErr = String(err?.stack || err);
      $("#twin-parts").innerHTML = '<li class="alert-empty">模型加载失败</li>';
      // 失败也要把过场遮罩关掉, 不能黑场卡死
      if (fadeEl) { fadeEl.classList.add("out"); fadeEl.classList.remove("on"); }
    });
  }

  // 拆解动画驱动(注意: clearScene 会清空 updaters, 必须在每次选设备后重新注册)
  const explodeDriver = (dt) => {
    explodeAnim += (explodeTarget - explodeAnim) * Math.min(1, dt * 4);
    if (current && Math.abs(explodeTarget - explodeAnim) > 0.001) {
      applyExplode(explodeAnim);
      updateLabels();
    }
  };

  // ===== 演示轮播(展会无人值守): 自动运镜 + 亮点部件脉冲 + 字幕; 任何交互即退出 =====
  const TOUR_SCENE_S = 20, TOUR_IDLE_S = 45;
  // 调试/开发场景: URL 加 ?tour=off 彻底禁用闲置自动开播(手动按钮不受影响)
  const TOUR_AUTO_OFF = new URLSearchParams(location.search).get("tour") === "off";
  // 巡检叙事程序注册表: 章节顺序 + 每站字幕 + 流转条标签
  const TOUR_PROGRAMS = {
    line: {
      ids: ["sorting_line", "kr210", "forklift", "voron_printer"],
      flow: ["视觉分拣", "六轴点焊", "叉车上架", "增材制造"],
      story: {
        sorting_line: "第一章 · 分拣：39 辊动力输送线过光幕按 SKU 类型摆臂分流",
        kr210: "第二章 · 点焊：KR210 重载六轴把工件装入夹具完成点焊",
        forklift: "第三章 · 叉运：平衡重叉车低位安全转运并举升上架",
        voron_printer: "第四章 · 增材：Voron 2.4 七千零件级 CoreXY 飞行龙门闭环打印",
      },
    },
  };
  let tourMode = false, tourSceneId = null, tourSceneT = 0, tourSlot = -1,
    tourParts = [], tourPrevHi = null, tourOrbit = { az: 0, R: 1, sinPhi: 0, cosPhi: 1 }, idleT = 0,
    tourProgram = null, tourProgramKey = null;
  const setCaption = (html, show = true) => {
    const c = $("#twin-caption"); if (!c) return;
    c.innerHTML = html; c.classList.toggle("show", show);
  };
  function tourHighlight(part) {
    if (tourPrevHi) tourPrevHi.traverse((c) => {
      if (c.isMesh && c.userData._tourHi) {
        c.material.emissive.setHex(c.userData._prevEm);
        c.material.emissiveIntensity = c.userData._prevInt;
        delete c.userData._tourHi;
      }
    });
    tourPrevHi = part?.node ?? null;
    if (tourPrevHi) tourPrevHi.traverse((c) => {
      if (c.isMesh && c.material?.emissive) {
        c.userData._prevEm = c.material.emissive.getHex();
        c.userData._prevInt = c.material.emissiveIntensity;
        c.userData._tourHi = true;
        c.material.emissive.setHex(0x3cf0d0);
        c.material.emissiveIntensity = 0.85;   // 初值柔和, 呼吸脉冲由 tourDriver 逐帧驱动
      }
    });
  }
  function startTour(programKey = null) {
    tourMode = true; tourSceneId = null; idleT = 0; tourProgram = programKey ? TOUR_PROGRAMS[programKey] : null;
    tourProgramKey = programKey;
    $("#twin-tour")?.classList.toggle("active", !programKey);
    $("#twin-line")?.classList.toggle("active", programKey === "line");
    if (tourProgram) selectEquipment(tourProgram.ids[0]);   // 巡检从第一章开始
  }
  function stopTour() {
    idleT = 0;
    if (!tourMode) return;
    tourMode = false; tourProgram = null; tourProgramKey = null;
    tourHighlight(null);
    setCaption("", false);
    const flow = $("#twin-flow"); if (flow) flow.hidden = true;
    $("#twin-tour")?.classList.remove("active");
    $("#twin-line")?.classList.remove("active");
  }
  const tourDriver = (dt) => {
    if (!tourMode) {   // 闲置计时: 仅在无后端决策控制时自动开播
      idleT += dt;
      if (idleT > TOUR_IDLE_S && current && !TOUR_AUTO_OFF && !liveBackendSnap) startTour();
      return;
    }
    if (!current) return;   // 等下一台加载
    if (current.def.id !== tourSceneId) {   // 每场初始化(构图完成后取景)
      tourSceneId = current.def.id; tourSceneT = 0; tourSlot = -1;
      // 绝对球坐标取景(方位/半径/仰角正弦) —— 运镜每帧由初值推算, 不做增量乘法(增量会复利漂移)
      const o = stage.camera.position.clone().sub(stage.controls.target);
      const rXZ = Math.hypot(o.x, o.z);
      tourOrbit = { az: Math.atan2(o.x, o.z), R: o.length(), sinPhi: o.y / o.length(), cosPhi: rXZ / o.length() };
      tourHighlight(null);
      // 亮点候选: 运动机械优先(吊具/小车/吊钩/分流杆/货叉/轮毂/法兰…), 同类里小件优先;
      // 直接按体积只会选中大梁/塔身这种整構件, 高光一打满屏糊光
      const INTERESTING = /spreader|trolley|hook|diverter|carriage|fork|hub|nacelle|container|chute|arch|jaw|flange|wrist|gripper|mast_l|mast_r|jib|platform|lightbar/i;
      tourParts = [...current.parts]
        .map((p) => { const b = new THREE.Box3().setFromObject(p.node); const s = b.getSize(new THREE.Vector3()); return { node: p.node, raw: p.node.name ?? "", name: p.name, vol: s.x * s.y * s.z }; })
        .sort((a, b) => ((INTERESTING.test(b.raw) ? 1 : 0) - (INTERESTING.test(a.raw) ? 1 : 0)) || (a.vol - b.vol))
        .slice(0, 3);
      setCaption(tourProgram?.story?.[current.def.id]
        ? `<strong>${current.def.name}</strong><span>${tourProgram.story[current.def.id]}</span>`
        : `<strong>${current.def.name}</strong><span>${current.def.pitch ?? current.def.subtitle}</span>`);
      // 章节流转条: 巡检程序显示, 按程序的 flow 标签动态生成, 当前章高亮 + 换章箭头脉冲
      const flow = $("#twin-flow");
      if (flow) {
        if (tourProgram) {
          const ci = tourProgram.ids.indexOf(current.def.id);
          flow.innerHTML = tourProgram.flow.map((f, i) =>
            `<span class="${i === ci ? "on" : ""}">${f}</span>`).join("<i>→</i>");
          flow.hidden = false;
          const arrow = flow.querySelectorAll("i")[ci - 1] ?? null;   // 流入当前章的那根箭头
          if (arrow) { arrow.classList.add("pulse"); }
        } else flow.hidden = true;
      }
    }
    tourSceneT += dt;
    // 运镜: 每场 220° 环绕 + 先推后拉的呼吸距离 + 轻微俯仰起伏(全部由初值绝对推算)
    const cam = stage.camera, tgt = stage.controls.target;
    const prog = Math.min(tourSceneT / TOUR_SCENE_S, 1);
    const az = tourOrbit.az + prog * Math.PI * 2 * 0.61;
    const R = tourOrbit.R * (1 - 0.12 * Math.sin(prog * Math.PI));
    const y = tgt.y + tourOrbit.sinPhi * R + Math.sin(tourSceneT * 0.45) * R * 0.05;
    cam.position.set(tgt.x + tourOrbit.cosPhi * R * Math.sin(az), y, tgt.z + tourOrbit.cosPhi * R * Math.cos(az));
    // 高光呼吸: 柔和脉冲(bloom 前 0.85±0.45, 大件也不炸白)
    if (tourPrevHi) tourPrevHi.traverse((c) => { if (c.isMesh && c.userData._tourHi) c.material.emissiveIntensity = 0.85 + Math.sin(tourSceneT * 4.5) * 0.45; });
    // 亮点节拍: 4s / 9s / 14s 三个, 字幕同步
    if (tourSceneT >= 4) {
      const slot = Math.min(2, Math.floor((tourSceneT - 4) / 5));
      if (slot !== tourSlot && tourParts[slot]) {
        tourSlot = slot;
        tourHighlight(tourParts[slot]);
        setCaption(`<em>亮点部件</em><strong>${tourParts[slot].name}</strong>`);
      }
    }
    if (tourSceneT >= TOUR_SCENE_S) {   // 换下一台(缓存已热, 秒切; 巡检程序按章节顺序)
      if (tourProgram) {
        const i = tourProgram.ids.indexOf(current.def.id);
        selectEquipment(tourProgram.ids[(i + 1) % tourProgram.ids.length]);
      } else {
        const idx = EQUIPMENT.findIndex((e) => e.id === current.def.id);
        selectEquipment(EQUIPMENT[(idx + 1) % EQUIPMENT.length].id);
      }
    }
  };

  $("#twin-explode").onclick = () => {    explodeTarget = explodeTarget > 0.5 ? 0 : 1;
    $("#twin-explode").classList.toggle("active", explodeTarget > 0.5);
    // 拆解后部件散得更开: 相机按爆炸终态精确构图(部件中心+名牌环带全部入画)
    // —— manualFrame 场景(整厂/猫头鹰/眼镜OS)钉死机位, 开合都不自动重构图(否则装配后视角飞掉)
    if (current && !current.def.manualFrame) {
      const bb = new THREE.Box3().setFromObject(current.root);
      if (explodeTarget > 0.5) {
        const R = current.labelRadius ?? 2;
        for (const p of current.parts) {
          const ec = p.off
            ? p.center.clone().addScaledVector(p.off, current.scale)
            : p.center.clone().addScaledVector(p.worldDir ?? new THREE.Vector3(), p.distWorld ?? 0);
          bb.expandByPoint(ec);
          const a = (p.labelIdx ?? 0) * 2.399963;
          bb.expandByPoint(new THREE.Vector3(ec.x + Math.cos(a) * R, ec.y + 0.12, ec.z + Math.sin(a) * R));
        }
        bb.expandByScalar(current.size * 0.09);   // 部件半径与名牌自身尺寸的余量
      }
      composeFrame(bb);
    }
  };

  // 演示轮播: 按钮手动开关; 任何交互(拖/点/滚轮/按键, 含侧栏换机)立即退出轮播交还控制权
  // —— 监听挂 document: 侧栏在主界面而不在孪生容器内, 挂容器会导致点侧栏时闲置计时还在涨(轮播抢控制权)
  $("#twin-tour").onclick = () => { tourMode && !tourProgram ? stopTour() : (stopTour(), startTour()); };
  // 巡检程序(产线/港口): 同键再点退出, 互点切换
  $("#twin-line").onclick = () => { tourProgramKey === "line" ? stopTour() : (stopTour(), startTour("line")); };
  for (const ev of ["pointerdown", "wheel", "keydown"])
    document.addEventListener(ev, (e) => {
      if (!e.target?.closest?.("#twin-tour") && !e.target?.closest?.("#twin-line")) stopTour();
    }, { passive: true });

  // 部件清单点击 → 高亮该部件 + 弹功能注解卡(有注解时)
  $("#twin-parts").onclick = (e) => {
    const li = e.target.closest("[data-part]");
    if (!li || !current) return;
    const p = current.parts[Number(li.dataset.part)];
    if (!p) return;
    p.node.traverse((c) => {
      const m = c.material;
      if (m?.emissive) {
        if (c.userData.prevEmissive === undefined) {
          c.userData.prevEmissive = m.emissive.getHex();
          c.userData.prevIntensity = m.emissiveIntensity;
        }
        m.emissive.setHex(PALETTE.cyan);
        m.emissiveIntensity = 0.9;
        setTimeout(() => {
          m.emissive.setHex(c.userData.prevEmissive);
          m.emissiveIntensity = c.userData.prevIntensity ?? 1;
        }, 900);
      }
    });
    // 功能注解卡: 编号件按基础名查(门腿 3 → 门腿)
    const note = PART_NOTES[p.name.replace(/ \d+$/, "")];
    stage.onPick?.(note
      ? { title: p.name, lines: [["所属", current.def.name], ["功能", note]] }
      : { title: p.name, lines: [["所属", current.def.name]] });
  };

  const nav = $("#twin-nav");
  if (nav) {   // 独立页签模式遗留: 嵌入模式导航在实验台侧栏
    nav.innerHTML = EQUIPMENT_GROUPS.map((g) =>
      `<div class="twin-group-title">${g.title}</div>` +
      g.items.map((e) =>
        `<button class="twin-nav-item" data-scene="${e.id}" type="button"><i data-lucide="scan-line"></i><span>${e.name}</span></button>`).join("")
    ).join("");
    nav.onclick = (e) => {
      const b = e.target.closest("[data-scene]");
      if (b) selectEquipment(b.dataset.scene);
    };
  }
  $("#twin-side-toggle")?.addEventListener("click", () => {
    sideUserToggled = true;
    const nextCollapsed = !$("#twin-side")?.classList.contains("collapsed");
    setSideCollapsed(nextCollapsed);
    if (current && !current.def.manualFrame && explodeTarget < 0.5) {
      composeFrame(new THREE.Box3().setFromObject(current.root));
    }
  });
  $("#twin-back")?.addEventListener("click", () => opts.onBack?.());

  stage.onPick = (info) => {
    const card = $("#twin-pick");
    if (!info) { card.hidden = true; return; }
    card.innerHTML = `<div class="pick-head"><strong>${info.title}</strong><button class="pick-close" type="button"><i data-lucide="x"></i></button></div>
      <table>${info.lines.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("")}</table>`;
    card.hidden = false;
    card.querySelector(".pick-close").onclick = () => { card.hidden = true; };
    createIcons({ icons: TWIN_ICONS, root: card });
  };

  function fit() {
    const vp = container.querySelector(".twin-viewport") ?? container;
    if (vp && vp.clientWidth > 0) stage.resize(vp.clientWidth, vp.clientHeight);
  }
  const ro = new ResizeObserver(fit);
  ro.observe(container);

  stage.start();
  createIcons({ icons: TWIN_ICONS, root: container });
  // 后台静默预载: 首台设备就绪后按列表顺序把全部机型拉进缓存(loadModel/loadRobot 自带去重),
  // 展会现场点任何一台秒开; 逐台串行 + 间隙让帧, 不抢首屏带宽与主线程
  (async () => {
    await new Promise((r) => setTimeout(r, 3000));
    for (const def of EQUIPMENT) {
      try {
        if (def.robot) await loadRobot(def.robot, def.pose || null);
        else if (!def.build) await loadModel(def.file);   // 程序化装备无 GLB, 无需预载
      } catch { /* 预载失败无碍, 点到该台时再按需加载 */ }
      await new Promise((r) => setTimeout(r, 300));
    }
  })();
  window.__twin = { stage, selectScene: selectEquipment,
    getTaskState: () => ({ def: current?.def, count: shownCount, active: taskActive }),
    taskToggle, taskReset, applyBackendState };
  window.__THREE = THREE;
  window.__GLTFLoader = GLTFLoader;
  window.__OBJLoader = OBJLoader;
  window.__STLLoader = STLLoader;

  return {
    setActive(active) {
      if (active) { fit(); stage.start(); }
      else { stage.stop(); }
    },
    dispose() { ro.disconnect(); stage.stop(); },
    select: selectEquipment,
    applyBackendState,
  };
}
