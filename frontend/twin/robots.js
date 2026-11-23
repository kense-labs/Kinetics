// 真机 CAD 装配器: 直接读 MJCF XML + 官方网格, 在 three.js 里按连杆树装配
// (Menagerie 模型坐标系 = MJCF Z-up; 根组 -90°X 转到 Y-up)
import * as THREE from "three";
import { OBJLoader } from "three/addons/loaders/OBJLoader.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

const objLoader = new OBJLoader();
const stlLoader = new STLLoader();

// 主副本缓存: 每台机(按 key+pose)只装配一次, 调用方拿到的是 clone(共享几何/材质, 位姿独立)
// —— 重复进入同一机型不再重新下载/解析全部网格; 主副本永不上屏, 动画不会污染后续访客
const robotCache = new Map();

export async function loadRobot(key, poseOverride = null) {
  const ck = `${key}|${JSON.stringify(poseOverride ?? "home")}`;
  if (!robotCache.has(ck)) robotCache.set(ck, buildRobot(key, poseOverride));
  const master = await robotCache.get(ck);
  const group = master.group.clone(true);
  const links = [];
  group.traverse((o) => { if (o.userData?.linkIdx !== undefined) links[o.userData.linkIdx] = o; });
  return { group, links };
}

async function buildRobot(key, poseOverride = null) {
  const base = `/twin-assets/robots/${key}`;
  const xmlText = await (await fetch(`${base}/model.xml`)).text();
  const doc = new DOMParser().parseFromString(xmlText, "text/xml");

  // 网格名 → 文件名; 材质名 → rgba
  const meshFiles = {};
  const matColors = {};
  doc.querySelectorAll("asset > mesh").forEach((m) => {
    const name = m.getAttribute("name") || m.getAttribute("file").replace(/\.[^.]+$/, "");
    meshFiles[name] = m.getAttribute("file");
  });
  doc.querySelectorAll("asset > material").forEach((m) => {
    if (m.getAttribute("name") && m.getAttribute("rgba"))
      matColors[m.getAttribute("name")] = m.getAttribute("rgba").trim().split(/\s+/).map(Number);
  });
  // home 关键帧的关节角
  const homeQpos = poseOverride ??
    (doc.querySelector('keyframe > key[name="home"]')?.getAttribute("qpos") || "")
      .trim().split(/\s+/).filter(Boolean).map(Number);

  const root = new THREE.Group();
  root.rotation.x = -Math.PI / 2;   // MJCF Z-up → three.js Y-up
  const links = [];
  const jointStack = [];   // {group, axis} 按树的顺序

  function matOf(geom) {
    const matName = geom.getAttribute("material");
    const rgba = (matName && matColors[matName]) ||
      (geom.getAttribute("rgba") ? geom.getAttribute("rgba").trim().split(/\s+/).map(Number) : null) ||
      [0.72, 0.75, 0.78, 1];
    return new THREE.MeshStandardMaterial({
      color: new THREE.Color(rgba[0], rgba[1], rgba[2]),
      roughness: 0.52, metalness: 0.28,
    });
  }

  async function walk(body, parent) {
    const g = new THREE.Group();
    g.name = body.getAttribute("name") || "link";
    const pos = (body.getAttribute("pos") || "0 0 0").trim().split(/\s+/).map(Number);
    const quat = (body.getAttribute("quat") || "1 0 0 0").trim().split(/\s+/).map(Number);
    g.position.set(...pos);
    g.quaternion.set(quat[1], quat[2], quat[3], quat[0]);   // MJCF(wxyz) → THREE(xyzw)
    g.quaternion.normalize();   // MJCF 四元数常未归一化(如 "1 1 0 0"), 不规约会放大几何
    g.userData.linkIdx = links.length;   // clone 后按此回收连杆序列(见 loadRobot)
    parent.add(g);
    links.push(g);
    // 本体的关节(若有)记入关节栈, 稍后按 home 角旋转
    // MJCF 未写 axis 的铰链默认轴是 (0 0 1)
    const jnt = body.querySelector(":scope > joint");
    if (jnt && !["free", "slide"].includes(jnt.getAttribute("type") || "hinge")) {
      jointStack.push({
        group: g,
        axis: (jnt.getAttribute("axis") || "0 0 1").trim().split(/\s+/).map(Number),
      });
    }

    const jobs = [];
    body.querySelectorAll(":scope > geom[mesh]").forEach((geom) => {
      const cls = geom.getAttribute("class") || "";
      if (cls && !cls.includes("visual")) return;    // 只装视觉网格
      const meshRef = geom.getAttribute("mesh");
      const file = meshFiles[meshRef] || meshRef;
      const gpos = (geom.getAttribute("pos") || "0 0 0").trim().split(/\s+/).map(Number);
      jobs.push((async () => {
        const url = `${base}/${file}`;
        let obj;
        if (/\.stl$/i.test(file)) {
          const geo = stlLoader.parse(await (await fetch(url)).arrayBuffer());
          obj = new THREE.Mesh(geo, matOf(geom));
        } else {
          obj = await objLoader.loadAsync(url);
          const m = matOf(geom);
          obj.traverse((c) => { if (c.isMesh) c.material = m; });
        }
        obj.position.set(...gpos);
        obj.traverse((c) => { if (c.isMesh) { c.castShadow = true; c.receiveShadow = true; } });
        g.add(obj);
      })());
    });
    await Promise.all(jobs);
    for (const child of body.children) {
      if (child.tagName === "body") await walk(child, g);
    }
  }

  const world = doc.querySelector("worldbody");
  for (const body of world.children) {
    if (body.tagName === "body") await walk(body, root);
  }
  // 按 home 关键帧摆姿态: 从根到叶逐关节绕轴旋转
  jointStack.forEach((j, i) => {
    const angle = homeQpos[i] ?? 0;
    if (!angle) return;
    const axis = new THREE.Vector3(...j.axis).normalize();
    j.group.rotateOnAxis(axis, angle);
  });
  return { group: root, links };
}
