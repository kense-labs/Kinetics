import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

export class RobotScene {
  constructor(
    container,
    {
      label = "MuJoCo 机械臂三维场景",
      pixelRatio = 2,
      onError = () => {},
    } = {},
  ) {
    this.container = container;
    this.objects = new Map();
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color("#ecf1ef");
    this.camera = new THREE.PerspectiveCamera(36, 1, 0.01, 20);
    this.camera.up.set(0, 0, 1);
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, pixelRatio));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.02;
    this.renderer.domElement.setAttribute("aria-label", label);
    container.prepend(this.renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const envScene = new RoomEnvironment();
    this.pmremTarget = pmrem.fromScene(envScene, 0.04);
    envScene.dispose();
    pmrem.dispose();
    this.scene.environment = this.pmremTarget.texture;
    this.scene.environmentIntensity = 0.34;

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = 0.65;
    this.controls.maxDistance = 3.2;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    const hemisphere = new THREE.HemisphereLight(0xffffff, 0xa8bcb1, 1.18);
    hemisphere.position.set(0, 0, 3);
    this.scene.add(hemisphere);
    const light = new THREE.DirectionalLight(0xffffff, 2.15);
    light.position.set(-0.85, -1.15, 2.55);
    light.castShadow = true;
    light.shadow.mapSize.set(
      pixelRatio < 2 ? 512 : 2048,
      pixelRatio < 2 ? 512 : 2048,
    );
    Object.assign(light.shadow.camera, {
      left: -1.2,
      right: 1.2,
      top: 1.2,
      bottom: -1.2,
    });
    light.shadow.normalBias = 0.001;
    light.shadow.bias = -0.0001;
    this.scene.add(light);
    const fill = new THREE.DirectionalLight(0xdce9ff, 0.55);
    fill.position.set(1.1, 1.0, 1.45);
    this.scene.add(fill);
    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(200, 200),
      new THREE.MeshStandardMaterial({
        color: 0xecf1ef,
        roughness: 0.94,
        metalness: 0.0,
      }),
    );
    floor.position.z = -0.075;
    floor.receiveShadow = true;
    this.scene.add(floor);

    // Subtle engineering datum ring around workspace center
    const outerRing = new THREE.Mesh(
      new THREE.RingGeometry(0.62, 0.625, 96),
      new THREE.MeshBasicMaterial({
        color: 0xc5d5ce,
        transparent: true,
        opacity: 0.65,
      }),
    );
    outerRing.position.set(0.28, 0, -0.0742);
    this.scene.add(outerRing);
    const innerRing = new THREE.Mesh(
      new THREE.RingGeometry(0.32, 0.323, 72),
      new THREE.MeshBasicMaterial({
        color: 0xcfdcd6,
        transparent: true,
        opacity: 0.5,
      }),
    );
    innerRing.position.set(0.28, 0, -0.0742);
    this.scene.add(innerRing);

    this.robot = new THREE.Group();
    this.scene.add(this.robot);
    this.controls.addEventListener("change", () => this.requestRender());
    this.renderer.domElement.addEventListener("webglcontextlost", () => {
      if (!this.disposed) onError("三维渲染上下文已丢失，请刷新页面");
    });
    this.observer = new ResizeObserver(() => {
      if (!container.clientWidth || !container.clientHeight) return;
      this.renderer.setSize(
        container.clientWidth,
        container.clientHeight,
        false,
      );
      this.camera.aspect = container.clientWidth / container.clientHeight;
      this.camera.updateProjectionMatrix();
      this.requestRender();
    });
    this.observer.observe(container);
    this.cameraHome();
  }

  cameraHome() {
    this.camera.position.set(1.4, -1.65, 1.27);
    this.controls.target.set(0.32, 0, 0.24);
    this.controls.update();
    this.requestRender();
  }

  cameraTop() {
    this.camera.position.set(0.42, -0.001, 1.85);
    this.controls.target.set(0.4, 0, 0.05);
    this.controls.update();
    this.requestRender();
  }

  clearRobot() {
    for (const child of [...this.robot.children]) {
      child.geometry.dispose();
      child.material.dispose();
      this.robot.remove(child);
    }
    this.objects.clear();
  }

  load(data) {
    this.clearRobot();
    this.lastFrame = null;
    for (const item of data.geometries) {
      let geometry;
      if (item.type === 7) {
        const mesh = data.meshes[item.mesh];
        geometry = new THREE.BufferGeometry();
        geometry.setAttribute(
          "position",
          new THREE.Float32BufferAttribute(mesh.vertices.flat(), 3),
        );
        geometry.setIndex(mesh.faces.flat());
        geometry.computeVertexNormals();
      } else if (item.type === 6) {
        geometry = new THREE.BoxGeometry(...item.size.map((size) => size * 2));
      } else if (item.type === 2) {
        geometry = new THREE.SphereGeometry(item.size[0], 24, 16);
      } else if (item.type === 5) {
        geometry = new THREE.CylinderGeometry(
          item.size[0],
          item.size[0],
          item.size[1] * 2,
          32,
        );
        geometry.rotateX(Math.PI / 2);
      } else continue;
      const [red, green, blue, alpha] = item.color;
      const isTaskObj = /cube|target|pad|box|bin|barrier|peg|socket/i.test(
        item.name || "",
      );
      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(red, green, blue).convertSRGBToLinear(),
        roughness: isTaskObj ? 0.34 : 0.44,
        metalness: isTaskObj ? 0.05 : 0.2,
        transparent: alpha < 1,
        opacity: alpha,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.castShadow = mesh.receiveShadow = true;
      this.robot.add(mesh);
      this.objects.set(item.id, mesh);
    }
    this.requestRender();
  }

  render(frame) {
    if (
      !frame ||
      (this.lastFrame?.time === frame.time &&
        JSON.stringify(this.lastFrame.qpos) === JSON.stringify(frame.qpos))
    )
      return;
    this.lastFrame = frame;
    for (const [id, mesh] of this.objects) {
      const position = frame.positions[id],
        rotation = frame.rotations[id];
      if (!position || !rotation) continue;
      mesh.position.set(...position);
      mesh.quaternion.setFromRotationMatrix(
        new THREE.Matrix4().set(
          rotation[0],
          rotation[1],
          rotation[2],
          0,
          rotation[3],
          rotation[4],
          rotation[5],
          0,
          rotation[6],
          rotation[7],
          rotation[8],
          0,
          0,
          0,
          0,
          1,
        ),
      );
    }
    this.requestRender();
  }

  requestRender() {
    if (this.renderRequested || this.disposed) return;
    this.renderRequested = true;
    requestAnimationFrame(() => {
      this.renderRequested = false;
      if (
        this.disposed ||
        !this.container.clientWidth ||
        !this.container.clientHeight
      )
        return;
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
  }

  dispose() {
    this.disposed = true;
    this.observer.disconnect();
    this.controls.dispose();
    this.clearRobot();
    this.scene.traverse((object) => {
      object.geometry?.dispose();
      object.material?.dispose();
      object.shadow?.map?.dispose();
    });
    this.scene.environment = null;
    this.pmremTarget?.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}
