import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { SVGLoader } from "three/addons/loaders/SVGLoader.js";
import sourceData from "./masterplan-data.json";
import type { MasterplanData } from "./masterplan-types";

export type MasterplanScene = {
  blocks: { id: string; label: string }[];
  select: (id: string) => void;
  zoom: (factor: number) => void;
  dispose: () => void;
};

// All plan positions come from the existing PDF extraction. Depth is illustrative.
export function createMasterplanScene(
  host: HTMLDivElement,
  onSelect: (id: string) => void,
  onFailure: () => void,
): MasterplanScene {
  const plan = sourceData as MasterplanData;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "img");
  canvas.setAttribute(
    "aria-label",
    "Maqueta conceptual del plano. Usa las flechas para girar, más y menos para acercar, o el selector de manzana.",
  );
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  host.appendChild(canvas);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 120);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  controls.enablePan = false;
  controls.enableZoom = false; // Wheel and pinch remain available to the page.
  controls.minPolarAngle = Math.PI / 7;
  controls.maxPolarAngle = Math.PI / 2.55;
  controls.rotateSpeed = 0.5;
  controls.touches.ONE = THREE.TOUCH.ROTATE;
  controls.touches.TWO = THREE.TOUCH.DOLLY_PAN;
  canvas.style.touchAction = "pan-y pinch-zoom";
  scene.add(new THREE.HemisphereLight(0xf8ffe8, 0x51604b, 2));
  const sun = new THREE.DirectionalLight(0xfff5d8, 2);
  sun.position.set(-6, 12, 7);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  Object.assign(sun.shadow.camera, {
    left: -10,
    right: 10,
    top: 10,
    bottom: -10,
    near: 1,
    far: 35,
  });
  sun.shadow.bias = -0.0003;
  sun.shadow.normalBias = 0.015;
  sun.shadow.camera.updateProjectionMatrix();
  scene.add(sun);

  const group = new THREE.Group();
  scene.add(group);
  const meshes: THREE.Mesh<
    THREE.ExtrudeGeometry,
    THREE.MeshStandardMaterial
  >[] = [];
  const scale = 12 / Math.max(plan.viewBox[2], plan.viewBox[3]);
  const centerX = plan.viewBox[0] + plan.viewBox[2] / 2;
  const centerY = plan.viewBox[1] + plan.viewBox[3] / 2;
  const outlineMaterial = new THREE.LineBasicMaterial({
    color: 0x52664b,
    transparent: true,
    opacity: 0.42,
  });
  let frame = 0;
  let disposed = false;
  let transition: {
    start: number;
    from: THREE.Vector3;
    to: THREE.Vector3;
    targetFrom: THREE.Vector3;
    targetTo: THREE.Vector3;
  } | null = null;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  function requestRender() {
    if (!frame && !disposed) frame = requestAnimationFrame(render);
  }
  function render(time: number) {
    frame = 0;
    if (disposed) return;
    if (transition) {
      const progress = reducedMotion.matches
        ? 1
        : Math.min((time - transition.start) / 650, 1);
      const eased = 1 - (1 - progress) ** 3;
      camera.position.lerpVectors(transition.from, transition.to, eased);
      controls.target.lerpVectors(
        transition.targetFrom,
        transition.targetTo,
        eased,
      );
      controls.update();
      if (progress === 1) transition = null;
      else requestRender();
    }
    renderer.render(scene, camera);
  }
  function move(position: THREE.Vector3, target: THREE.Vector3) {
    transition = {
      start: performance.now(),
      from: camera.position.clone(),
      to: position,
      targetFrom: controls.target.clone(),
      targetTo: target,
    };
    requestRender();
  }
  function overview() {
    const distance = Math.max(18, 27 / camera.aspect);
    return new THREE.Vector3(distance * 0.45, distance * 0.72, distance * 0.62);
  }
  function select(id: string) {
    const block = plan.blocks.find((item) => item.id === id);
    for (const mesh of meshes) {
      const active = mesh.userData.blockId === id;
      mesh.material.color.set(active ? 0x39551f : 0x78935a);
      mesh.material.emissive.set(active ? 0x172808 : 0x000000);
    }
    if (block) {
      const target = new THREE.Vector3(
        ((block.bounds[0] + block.bounds[2]) / 2 - centerX) * scale,
        0,
        ((block.bounds[1] + block.bounds[3]) / 2 - centerY) * scale,
      );
      move(target.clone().add(new THREE.Vector3(3.5, 6, 5.5)), target);
    } else move(overview(), new THREE.Vector3());
    onSelect(block?.id ?? "");
  }
  function zoom(factor: number) {
    transition = null;
    const offset = camera.position.clone().sub(controls.target);
    offset.setLength(THREE.MathUtils.clamp(offset.length() * factor, 3, 34));
    move(controls.target.clone().add(offset), controls.target.clone());
  }
  function resize() {
    const { width, height } = host.getBoundingClientRect();
    if (!width || !height) return;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
    requestRender();
  }
  function pointerStart(event: PointerEvent) {
    transition = null;
    down.set(event.clientX, event.clientY);
  }
  const down = new THREE.Vector2();
  const raycaster = new THREE.Raycaster();
  function pointerEnd(event: PointerEvent) {
    if (down.distanceTo(new THREE.Vector2(event.clientX, event.clientY)) > 5)
      return;
    const bounds = canvas.getBoundingClientRect();
    raycaster.setFromCamera(
      new THREE.Vector2(
        ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
        -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
      ),
      camera,
    );
    const hit = raycaster.intersectObjects(meshes, false)[0];
    if (hit) select(hit.object.userData.blockId as string);
  }
  function keydown(event: KeyboardEvent) {
    const keys = [
      "ArrowLeft",
      "ArrowRight",
      "ArrowUp",
      "ArrowDown",
      "+",
      "=",
      "-",
      "Home",
    ];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    transition = null;
    if (event.key === "Home") {
      select("");
      return;
    }
    if (["+", "=", "-"].includes(event.key)) {
      zoom(event.key === "-" ? 1.25 : 0.8);
      return;
    }
    const offset = camera.position.clone().sub(controls.target);
    const orbit = new THREE.Spherical().setFromVector3(offset);
    if (event.key === "ArrowLeft") orbit.theta -= 0.12;
    if (event.key === "ArrowRight") orbit.theta += 0.12;
    if (event.key === "ArrowUp") orbit.phi -= 0.1;
    if (event.key === "ArrowDown") orbit.phi += 0.1;
    orbit.phi = THREE.MathUtils.clamp(
      orbit.phi,
      controls.minPolarAngle,
      controls.maxPolarAngle,
    );
    camera.position
      .copy(controls.target)
      .add(new THREE.Vector3().setFromSpherical(orbit));
    controls.update();
    requestRender();
  }
  function contextLost(event: Event) {
    event.preventDefault();
    onFailure();
    dispose();
  }
  function stopTransition() {
    transition = null;
  }
  const observer = new ResizeObserver(resize);
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    observer.disconnect();
    controls.dispose();
    canvas.removeEventListener("pointerdown", pointerStart);
    canvas.removeEventListener("pointerup", pointerEnd);
    canvas.removeEventListener("keydown", keydown);
    canvas.removeEventListener("webglcontextlost", contextLost);
    scene.traverse((object) => {
      if (
        object instanceof THREE.Mesh ||
        object instanceof THREE.LineSegments
      ) {
        object.geometry.dispose();
        const materials = Array.isArray(object.material)
          ? object.material
          : [object.material];
        for (const material of materials) material.dispose();
      }
    });
    outlineMaterial.dispose();
    sun.shadow.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
    canvas.remove();
  }

  try {
    const loader = new SVGLoader();
    for (const block of plan.blocks) {
      const paths = loader.parse(
        `<svg xmlns="http://www.w3.org/2000/svg"><path d="${block.path}"/></svg>`,
      ).paths;
      const shapes = paths.flatMap((path) => path.toShapes());
      // Reflect source coordinates before triangulation so top-face winding and
      // normals remain correct; mirroring a finished mesh inverts its lighting.
      const normalize = (path: THREE.Path) =>
        path
          .getPoints(3)
          .map(
            (point) =>
              new THREE.Vector2(
                (point.x - centerX) * scale,
                -(point.y - centerY) * scale,
              ),
          );
      const normalized = shapes.map((shape) => {
        const result = new THREE.Shape(normalize(shape));
        result.holes = shape.holes.map(
          (hole) => new THREE.Path(normalize(hole)),
        );
        return result;
      });
      const geometry = new THREE.ExtrudeGeometry(normalized, {
        depth: 0.18,
        bevelEnabled: true,
        bevelThickness: 0.008,
        bevelSize: 0.006,
        bevelSegments: 1,
        curveSegments: 3,
        steps: 1,
      });
      geometry.rotateX(-Math.PI / 2);
      const material = new THREE.MeshStandardMaterial({
        color: 0x78935a,
        roughness: 0.92,
        metalness: 0,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.userData.blockId = block.id;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
      meshes.push(mesh);
      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry, 44),
        outlineMaterial,
      );
      group.add(edges);
    }
    // A presentation plinth, not an inferred property boundary or terrain surface.
    const base = new THREE.Mesh(
      new THREE.BoxGeometry(
        plan.viewBox[2] * scale + 0.55,
        0.3,
        plan.viewBox[3] * scale + 0.55,
      ),
      new THREE.MeshStandardMaterial({ color: 0xe1e1cf, roughness: 1 }),
    );
    base.position.y = -0.165;
    base.receiveShadow = true;
    group.add(base);
    const rim = new THREE.LineSegments(
      new THREE.EdgesGeometry(base.geometry),
      new THREE.LineBasicMaterial({ color: 0xc4c9b1 }),
    );
    rim.position.copy(base.position);
    group.add(rim);
    resize();
    camera.position.copy(overview());
    controls.target.set(0, 0, 0);
    controls.update();
    controls.addEventListener("change", requestRender);
    controls.addEventListener("start", stopTransition);
    canvas.addEventListener("pointerdown", pointerStart);
    canvas.addEventListener("pointerup", pointerEnd);
    canvas.addEventListener("keydown", keydown);
    canvas.addEventListener("webglcontextlost", contextLost);
    observer.observe(host);
    requestRender();
  } catch (error) {
    dispose();
    throw error;
  }
  return {
    blocks: plan.blocks.map(({ id, label }) => ({ id, label })),
    select,
    zoom,
    dispose,
  };
}
