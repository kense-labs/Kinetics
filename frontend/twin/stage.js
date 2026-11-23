// 数字孪生: 3D 舞台外壳(渲染器/相机/灯光/拾取)
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { PALETTE } from "./kit.js";

export class TwinStage {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.18;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(PALETTE.bg);   // 纯深底色(用户明确要求)
    this.scene.fog = new THREE.Fog(PALETTE.bg, 130, 340);
    // 环境反射: 让金属件有真实高光层次(否则金属=黑)
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.55;
    this.camera = new THREE.PerspectiveCamera(46, 1, 0.1, 900);
    // robot-scene.js 会把全局 DEFAULT_UP 改成 Z-up(MuJoCo 惯例), 这里必须显式钉回 Y-up,
    // 且要在 new OrbitControls 之前(它在构造时读取 object.up)
    this.camera.up.set(0, 1, 0);
    this.camera.position.set(46, 34, 46);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.minDistance = 1.2;
    this.controls.maxDistance = 220;
    this.controls.target.set(0, 4, 0);

    const hemi = new THREE.HemisphereLight(0x9cc0e4, 0x141a22, 1.25);
    const key = new THREE.DirectionalLight(0xfff2df, 2.45);
    key.position.set(38, 55, 22);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, { left: -80, right: 80, top: 80, bottom: -80, far: 220 });
    key.shadow.camera.updateProjectionMatrix();
    key.shadow.bias = -0.0006;
    const fill = new THREE.DirectionalLight(0x3b6ea5, 0.55);
    fill.position.set(-30, 24, -34);
    this.scene.add(hemi, key, key.target, fill);
    this.key = key;   // fitShadow 要按模型包围盒重定光源与阴影视锥

    // 辉光后处理: 发光体泛光(孪生大屏的核心质感来源) — 须在相机就绪后创建
    // 注意: antialias:true 只管直渲染, EffectComposer 走离屏 RT 必须显式开 MSAA samples,
    // 否则 CAD 硬边全是锯齿(像低模玩具); HalfFloat 是 bloom 精度要求, 不能省
    const dbSize = this.renderer.getDrawingBufferSize(new THREE.Vector2());
    // MSAA 8x: 塔吊桁架/岸桥拉杆这类亚像素细件的边缘质量是"玩具 vs 专业"的分水岭, M5 上实测代价可忽略
    const msaaRT = new THREE.WebGLRenderTarget(dbSize.x, dbSize.y, { samples: 8, type: THREE.HalfFloatType });
    this.composer = new EffectComposer(this.renderer, msaaRT);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1280, 800), 0.30, 0.45, 1.25);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());

    this.updaters = [];
    this.pickables = [];
    this.ray = new THREE.Raycaster();
    this.clock = new THREE.Clock();
    this.highlighted = null;
    this.onPick = null;
    this.running = false;
    canvas.addEventListener("pointerdown", (e) => this.pick(e));
    // GPU 上下文丢失自愈: 丢失时停循环, 恢复后自动重启(three 会重建 GPU 资源)
    canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); this.stop(); });
    canvas.addEventListener("webglcontextrestored", () => this.start());
  }
  add(obj, updater, pickInfo) {
    this.scene.add(obj);
    if (updater) this.updaters.push(updater);
    if (pickInfo) {
      obj.userData.pickRoot = true;
      obj.traverse((c) => { c.userData.pick = pickInfo; });
      this.pickables.push(obj);
    }
  }
  pick(e) {
    const r = this.canvas.getBoundingClientRect();
    const nx = ((e.clientX - r.left) / r.width) * 2 - 1;
    const ny = -((e.clientY - r.top) / r.height) * 2 + 1;
    this.ray.setFromCamera(new THREE.Vector2(nx, ny), this.camera);
    const hits = this.ray.intersectObjects(this.pickables, true);
    const info = hits.find((h) => h.object.userData.pick)?.object.userData.pick ?? null;
    if (this.highlighted) {
      this.highlighted.traverse((c) => {
        const m = c.material;
        if (m?.emissive && c.userData.prevEmissive !== undefined) {
          m.emissive.setHex(c.userData.prevEmissive);
          m.emissiveIntensity = c.userData.prevIntensity ?? 1;
        }
      });
      this.highlighted = null;
    }
    if (info && hits[0]) {
      let root = hits[0].object;
      while (root && !root.userData.pickRoot) root = root.parent;
      const target = root ?? hits[0].object;
      this.highlighted = target;
      target.traverse((c) => {
        const m = c.material;
        if (m?.emissive) {
          if (c.userData.prevEmissive === undefined) {
            c.userData.prevEmissive = m.emissive.getHex();
            c.userData.prevIntensity = m.emissiveIntensity;
          }
          m.emissive.setHex(PALETTE.cyan);
          m.emissiveIntensity = 0.55;
        }
      });
    }
    this.onPick?.(info);
  }
  start() {
    if (this.running) return;
    this.running = true;
    const loop = () => {
      if (!this.running) return;
      requestAnimationFrame(loop);
      const dt = Math.min(this.clock.getDelta(), 0.1);
      const t = this.clock.elapsedTime;
      try {
        for (const u of this.updaters) u(dt, t);
        this.controls.update();
        this.composer.render();
        this.afterRender?.();   // 画中画/监控墙等后置视口(主渲染后再画剪裁区)
      } catch (err) {
        // 单个更新器异常不能冻结渲染循环(否则画布黑帧)
        if (!this._loopErrLogged) { this._loopErrLogged = true; console.error("stage loop error", err); }
      }
    };
    loop();
  }
  stop() { this.running = false; }
  // 阴影视锥按模型包围盒收紧: 默认 ±80m 是给大场景的, 小设备下 2048 贴图摊到 160m²
  // 只剩 ~8cm/texel(一团糊); 贴合后毫米级 texel, 接触阴影才锐利
  fitShadow(bb) {
    const size = bb.getSize(new THREE.Vector3());
    const ctr = bb.getCenter(new THREE.Vector3());
    const half = size.length() * 0.62 + 0.3;
    const dir = this.key.position.clone().sub(this.key.target.position).normalize();
    this.key.position.copy(ctr).addScaledVector(dir, Math.max(60, size.length() * 3));
    this.key.target.position.copy(ctr);
    Object.assign(this.key.shadow.camera, { left: -half, right: half, top: half, bottom: -half, near: 1, far: Math.max(160, size.length() * 6) });
    this.key.shadow.camera.updateProjectionMatrix();
  }
  resize(w, h) {
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }
  resetCamera(pos, target) {
    this.camera.position.set(...pos);
    this.controls.target.set(...target);
  }
  clearScene() {
    this.updaters = [];
    this.pickables = [];
    this.highlighted = null;
    // key.target 不是 Light 会被 clear 掉, 必须跟着光源一起保留(否则阴影方向丢失)
    const keep = this.scene.children.filter((c) => c.isLight || c === this.key.target);
    this.scene.clear();
    this.scene.add(...keep);
  }
}
