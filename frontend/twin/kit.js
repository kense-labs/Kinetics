// 数字孪生: 共享 3D 工具(材质/标签/地面/路径/数据流光点)
import * as THREE from "three";

export const PALETTE = {
  bg: 0x0a0f16, ground: 0x232e3b, gridMinor: 0x33424f, gridMajor: 0x4a6076,
  steel: 0x4f6076, steelDark: 0x36435a, concrete: 0x5d6b7e,
  cyan: 0x22d3ee, amber: 0xf59e0b, green: 0x34d399, red: 0xef4444,
  blue: 0x3b82f6, violet: 0x8b5cf6, white: 0xe5edf5,
};

export function mat(color, opts = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.66, metalness: 0.1, ...opts });
}
export function glow(color, intensity = 1.6) {
  return new THREE.MeshStandardMaterial({
    color: 0x0b0f14, emissive: color, emissiveIntensity: intensity, roughness: 0.4, metalness: 0.1,
  });
}
export function box(w, h, d, m, x = 0, y = 0, z = 0) {
  const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
  b.position.set(x, y, z);
  b.castShadow = true; b.receiveShadow = true;
  return b;
}
export function cyl(rt, rb, h, m, x = 0, y = 0, z = 0, seg = 20) {
  const c = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m);
  c.position.set(x, y, z);
  c.castShadow = true; c.receiveShadow = true;
  return c;
}
export function label(text, size = 1, color = "#9fd8ef", bg = "rgba(8,14,22,0.72)") {
  const pad = 16, fs = 44;
  const cv = document.createElement("canvas");
  const ctx = cv.getContext("2d");
  ctx.font = `600 ${fs}px "PingFang SC", "Microsoft YaHei", sans-serif`;
  const tw = ctx.measureText(text).width;
  cv.width = Math.ceil(tw + pad * 2); cv.height = fs + pad * 2;
  const c2 = cv.getContext("2d");
  c2.fillStyle = bg;
  c2.beginPath(); c2.roundRect(0, 0, cv.width, cv.height, 12); c2.fill();
  c2.font = `600 ${fs}px "PingFang SC", "Microsoft YaHei", sans-serif`;
  c2.fillStyle = color; c2.textBaseline = "middle"; c2.textAlign = "center";
  c2.fillText(text, cv.width / 2, cv.height / 2 + 2);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
  const s = size * 0.011;
  sp.scale.set(cv.width * s, cv.height * s, 1);
  return sp;
}
export function ground(size = 120) {
  const g = new THREE.Group();
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(size * 2.4, size * 2.4),
    mat(PALETTE.ground, { roughness: 0.9, metalness: 0.05 }));
  plane.rotation.x = -Math.PI / 2;
  plane.receiveShadow = true;
  g.add(plane);
  const grid = new THREE.GridHelper(size * 2.4, Math.round(size * 1.2), PALETTE.gridMajor, PALETTE.gridMinor);
  grid.material.transparent = true; grid.material.opacity = 0.55;
  grid.position.y = 0.01;
  g.add(grid);
  return g;
}

// 场地发光边界线(孪生大屏标志性的场地框定)
export function siteBoundary(w, d, color = PALETTE.cyan, y = 0.03) {
  const g = new THREE.Group();
  const m = glow(color, 1.9);
  const t = 0.14;
  const n = box(w, 0.035, t, m, 0, y, -d / 2);
  const s = box(w, 0.035, t, m, 0, y, d / 2);
  const e = box(t, 0.035, d, m, w / 2, y, 0);
  const w2 = box(t, 0.035, d, m, -w / 2, y, 0);
  for (const b of [n, s, e, w2]) { b.castShadow = false; b.receiveShadow = false; g.add(b); }
  return g;
}

// 斑马线
export function crosswalk(x, z, width, across = "x") {
  const g = new THREE.Group();
  const n = Math.floor(width / 0.9);
  for (let i = 0; i < n; i++) {
    const s = across === "x"
      ? box(0.45, 0.02, 0.9, glow(0xd8dee6, 0.35), 0, 0, -width / 2 + i * 0.9 + 0.45)
      : box(0.9, 0.02, 0.45, glow(0xd8dee6, 0.35), -width / 2 + i * 0.9 + 0.45, 0, 0);
    s.castShadow = false;
    g.add(s);
  }
  g.position.set(x, 0.14, z);
  return g;
}

// 地面警示虚线(AGV 通道等)
export function dashedLane(pts, color = 0xc8a84a) {
  const g = new THREE.Group();
  for (let i = 0; i < pts.length - 1; i++) {
    const [x1, z1] = pts[i], [x2, z2] = pts[i + 1];
    const len = Math.hypot(x2 - x1, z2 - z1);
    const n = Math.floor(len / 1.6);
    for (let j = 0; j < n; j += 2) {
      const f0 = j / n, f1 = Math.min(1, (j + 1) / n);
      const cx = x1 + (x2 - x1) * (f0 + f1) / 2, cz = z1 + (z2 - z1) * (f0 + f1) / 2;
      const segLen = (f1 - f0) * len;
      const seg = box(segLen, 0.02, 0.16, glow(color, 0.55), cx, 0.06, cz);
      seg.rotation.y = -Math.atan2(z2 - z1, x2 - x1);
      seg.castShadow = false;
      g.add(seg);
    }
  }
  return g;
}
export class PathRunner {
  constructor(pts, speed, loop = true) {
    this.pts = pts; this.speed = speed; this.loop = loop;
    this.lens = []; this.total = 0;
    for (let i = 0; i < pts.length - 1; i++) {
      const l = pts[i].distanceTo(pts[i + 1]);
      this.lens.push(l); this.total += l;
    }
  }
  pos(t) {
    let d = this.loop ? (t * this.speed) % this.total : Math.min(t * this.speed, this.total);
    for (let i = 0; i < this.lens.length; i++) {
      if (d <= this.lens[i]) {
        const dir = this.pts[i + 1].clone().sub(this.pts[i]).normalize();
        return { p: this.pts[i].clone().addScaledVector(dir, d), dir };
      }
      d -= this.lens[i];
    }
    const dir = this.pts[this.pts.length - 1].clone().sub(this.pts[this.pts.length - 2]).normalize();
    return { p: this.pts[this.pts.length - 1].clone(), dir };
  }
}
export function flowDots(a, b, n, color = PALETTE.cyan) {
  const g = new THREE.Group();
  const dots = [];
  for (let i = 0; i < n; i++) {
    const d = box(0.32, 0.12, 0.12, glow(color, 2.2));
    d.castShadow = false;
    dots.push(d); g.add(d);
  }
  const dir = b.clone().sub(a);
  return {
    group: g,
    update(t) {
      for (let i = 0; i < n; i++) {
        const f = ((t * 0.35 + i / n) % 1);
        dots[i].position.copy(a).addScaledVector(dir, f);
        dots[i].lookAt(dots[i].position.clone().add(dir));
      }
    },
  };
}

// 影棚展台: 圆形地台 + 径向渐隐 + 微光外圈
export function studioStage(radius = 4.2) {
  const g = new THREE.Group();
  const cv = document.createElement("canvas");
  cv.width = cv.height = 512;
  const ctx = cv.getContext("2d");
  const grad = ctx.createRadialGradient(256, 256, 40, 256, 256, 256);
  grad.addColorStop(0, "#3a4552");
  grad.addColorStop(0.55, "#232c38");
  grad.addColorStop(1, "#0a0f16");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 512, 512);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const disc = new THREE.Mesh(
    new THREE.CircleGeometry(radius, 64),
    new THREE.MeshStandardMaterial({ map: tex, roughness: 0.55, metalness: 0.22 }));   // 抛光地坪微反光
  disc.rotation.x = -Math.PI / 2;
  disc.receiveShadow = true;
  g.add(disc);
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(radius * 0.985, radius, 96),
    new THREE.MeshStandardMaterial({ color: 0x0b0f14, emissive: PALETTE.cyan, emissiveIntensity: 1.4, transparent: true, opacity: 0.9 }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.005;
  g.add(ring);
  return g;
}

// 相机按包围盒自动构图(目标点压到模型中下部, 让地台进入画面; 竖屏视口自动拉远)
export function frameCamera(stage, bb, elevationDeg = 25, azimuthDeg = 38, margin = 2.1) {
  const size = bb.getSize(new THREE.Vector3());
  const center = bb.getCenter(new THREE.Vector3());
  const diag = size.length();
  const asp = stage.camera.aspect || 1;
  const portraitFit = asp >= 1 ? 1 : Math.min(2.6, 1 / (asp * 1.25));
  const dist = Math.max(1.4, diag * margin * portraitFit);
  const az = (azimuthDeg * Math.PI) / 180, el = (elevationDeg * Math.PI) / 180;
  const ty = Math.min(center.y, size.y * 0.42);
  stage.resetCamera(
    [center.x + dist * Math.cos(el) * Math.sin(az),
     ty + dist * Math.sin(el),
     center.z + dist * Math.cos(el) * Math.cos(az)],
    [center.x, ty, center.z]);
}
