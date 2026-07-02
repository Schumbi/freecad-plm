import * as THREE from "./vendor/three/build/three.module.js";
import { OrbitControls } from "./vendor/three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "./vendor/three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "./vendor/three/examples/jsm/loaders/3MFLoader.js";

const dialog = document.getElementById("model-viewer-dialog");
const titleElement = document.getElementById("model-viewer-title");
const formatElement = document.getElementById("model-viewer-format");
const canvasHost = document.getElementById("model-viewer-canvas");
const statusElement = document.getElementById("model-viewer-status");
const resetButton = document.getElementById("model-viewer-reset");
const wireframeButton = document.getElementById("model-viewer-wireframe");
const downloadLink = document.getElementById("model-viewer-download");

let renderer;
let scene;
let camera;
let controls;
let currentObject;
let animationFrame;
let wireframe = false;

function setStatus(message, visible = true) {
  statusElement.textContent = message;
  statusElement.hidden = !visible;
}

function ensureScene() {
  if (renderer) return;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x20282d);

  camera = new THREE.PerspectiveCamera(45, 16 / 9, 0.1, 100000);
  camera.position.set(120, 100, 120);

  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  canvasHost.appendChild(renderer.domElement);

  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  scene.add(new THREE.HemisphereLight(0xffffff, 0x6f7f88, 2.2));
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.8);
  keyLight.position.set(80, 120, 90);
  scene.add(keyLight);

  const axes = new THREE.AxesHelper(60);
  axes.name = "viewer-axes";
  scene.add(axes);

  window.addEventListener("resize", resizeRenderer);
}

function resizeRenderer() {
  if (!renderer || !camera) return;
  const rect = canvasHost.getBoundingClientRect();
  const width = Math.max(rect.width, 1);
  const height = Math.max(rect.height, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function animate() {
  if (!renderer) return;
  controls.update();
  renderer.render(scene, camera);
  animationFrame = requestAnimationFrame(animate);
}

function clearModel() {
  if (!currentObject) return;
  scene.remove(currentObject);
  currentObject.traverse((item) => {
    if (item.geometry) item.geometry.dispose();
    if (item.material) {
      const materials = Array.isArray(item.material) ? item.material : [item.material];
      materials.forEach((material) => material.dispose());
    }
  });
  currentObject = null;
}

function setWireframe(enabled) {
  wireframe = enabled;
  if (!currentObject) return;
  currentObject.traverse((item) => {
    if (!item.material) return;
    const materials = Array.isArray(item.material) ? item.material : [item.material];
    materials.forEach((material) => {
      material.wireframe = wireframe;
      material.needsUpdate = true;
    });
  });
}

function fitCamera(object) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) {
    camera.position.set(120, 100, 120);
    controls.target.set(0, 0, 0);
    controls.update();
    return;
  }

  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.length() * 0.5, 1);
  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * camera.aspect);
  const fitFov = Math.min(verticalFov, horizontalFov);
  const distance = (radius * 1.45) / Math.sin(fitFov / 2);
  const viewDirection = new THREE.Vector3(1, 0.75, 1).normalize();

  camera.near = Math.max(distance / 500, 0.01);
  camera.far = distance * 500;
  camera.position.copy(center).addScaledVector(viewDirection, distance);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.minDistance = Math.max(radius * 0.05, 0.01);
  controls.maxDistance = distance * 20;
  controls.update();
}

function materialForGeometry(geometry) {
  if (geometry.hasAttribute("color")) {
    return new THREE.MeshStandardMaterial({
      roughness: 0.62,
      metalness: 0.05,
      vertexColors: true,
      wireframe,
    });
  }
  return new THREE.MeshStandardMaterial({
    color: 0xb7c7d1,
    roughness: 0.62,
    metalness: 0.05,
    wireframe,
  });
}

async function fetchModel(sourceUrl) {
  const response = await fetch(sourceUrl, {
    credentials: "same-origin",
    headers: { "X-Requested-With": "XMLHttpRequest" },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `3D-Modell konnte nicht geladen werden (${response.status}).`);
  }
  return response.arrayBuffer();
}

function parseModel(buffer, format) {
  if (format === "3mf") {
    const object = new ThreeMFLoader().parse(buffer);
    object.rotation.set(-Math.PI / 2, 0, 0);
    return object;
  }

  const geometry = new STLLoader().parse(buffer);
  geometry.computeVertexNormals();
  return new THREE.Mesh(geometry, materialForGeometry(geometry));
}

async function openViewer(trigger) {
  ensureScene();
  dialog.hidden = false;
  document.body.classList.add("modal-open");
  resizeRenderer();
  setStatus("3D-Modell wird geladen...");
  clearModel();

  const sourceUrl = trigger.dataset.modelViewerSource;
  const format = trigger.dataset.modelViewerFormat || "stl";
  titleElement.textContent = trigger.dataset.modelViewerTitle || "3D-Modell";
  formatElement.textContent = format.toUpperCase();
  downloadLink.href = trigger.dataset.modelViewerDownload || sourceUrl;

  try {
    const buffer = await fetchModel(sourceUrl);
    currentObject = parseModel(buffer, format);
    scene.add(currentObject);
    setWireframe(wireframe);
    fitCamera(currentObject);
    setStatus("", false);
    if (!animationFrame) animate();
  } catch (error) {
    setStatus(error.message || "3D-Modell konnte nicht angezeigt werden.");
  }
}

document.addEventListener("click", (event) => {
  const trigger = event.target.closest("[data-model-viewer-source]");
  if (!trigger) return;
  event.preventDefault();
  openViewer(trigger);
});

resetButton?.addEventListener("click", () => {
  if (currentObject) fitCamera(currentObject);
});

wireframeButton?.addEventListener("click", () => {
  setWireframe(!wireframe);
  wireframeButton.classList.toggle("btn-primary", wireframe);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && dialog && dialog.hidden && animationFrame) {
    cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }
});
