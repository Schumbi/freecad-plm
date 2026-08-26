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
const annotateButton = document.getElementById("model-viewer-annotate");
const annotationForm = document.getElementById("model-viewer-annotation-form");
const annotationText = document.getElementById("model-viewer-annotation-text");
const annotationCancel = document.getElementById("model-viewer-annotation-cancel");

let renderer;
let scene;
let camera;
let controls;
let currentObject;
let animationFrame;
let wireframe = false;
let activeLoadId = 0;
let canvasResizeObserver;
let annotationsUrl = "";
let annotationMode = false;
let pendingAnchor = null;
let pendingCamera = null;
let annotationMarkers;

class ViewerHttpError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

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

  annotationMarkers = new THREE.Group();
  annotationMarkers.name = "viewer-annotations";
  scene.add(annotationMarkers);

  window.addEventListener("resize", resizeRenderer);
  if (window.ResizeObserver) {
    canvasResizeObserver = new ResizeObserver(resizeRenderer);
    canvasResizeObserver.observe(canvasHost);
  }
}

function resizeRenderer() {
  if (!renderer || !camera) return;
  const rect = canvasHost.getBoundingClientRect();
  const width = Math.max(rect.width, 1);
  const height = Math.max(rect.height, 1);
  const nextAspect = width / height;
  const aspectChanged = Math.abs(camera.aspect - nextAspect) > 0.05;
  renderer.setSize(width, height, false);
  camera.aspect = nextAspect;
  camera.updateProjectionMatrix();

  if (aspectChanged && currentObject) {
    const viewDirection = camera.position.clone().sub(controls.target).normalize();
    fitCamera(currentObject, viewDirection);
  }
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
  clearAnnotationMarkers();
}

function clearAnnotationMarkers() {
  if (!annotationMarkers) return;
  while (annotationMarkers.children.length) {
    const marker = annotationMarkers.children[0];
    annotationMarkers.remove(marker);
    marker.geometry?.dispose();
    marker.material?.dispose();
  }
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

function fitCamera(object, viewDirection = new THREE.Vector3(1, 0.75, 1).normalize()) {
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
    throw new ViewerHttpError(
      text || `3D-Modell konnte nicht geladen werden (${response.status}).`,
      response.status,
    );
  }
  return response.arrayBuffer();
}

function csrfToken() {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    credentials: "same-origin",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      ...(options.method === "POST" ? { "X-CSRFToken": csrfToken() } : {}),
      ...(options.headers || {}),
    },
  });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : { message: await response.text() };
  if (!response.ok) {
    throw new ViewerHttpError(
      payload.error || payload.message || `Anfrage fehlgeschlagen (${response.status}).`,
      response.status,
    );
  }
  return payload;
}

function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
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
  const loadId = ++activeLoadId;
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
  annotationsUrl = trigger.dataset.modelViewerAnnotations || "";
  annotateButton.hidden = trigger.dataset.modelViewerCanAnnotate !== "1" || !annotationsUrl;
  cancelAnnotation();

  try {
    const buffer = await loadModelBuffer(trigger, sourceUrl, loadId);
    if (loadId !== activeLoadId) return;
    currentObject = parseModel(buffer, format);
    scene.add(currentObject);
    setWireframe(wireframe);
    fitCamera(currentObject);
    await loadViewerAnnotations();
    setStatus("", false);
    if (!animationFrame) animate();
  } catch (error) {
    setStatus(error.message || "3D-Modell konnte nicht angezeigt werden.");
  }
}

function markerRadius() {
  if (!currentObject) return 1;
  const size = new THREE.Box3()
    .setFromObject(currentObject)
    .getSize(new THREE.Vector3());
  return Math.max(size.length() / 120, 0.5);
}

function addAnnotationMarker(annotation) {
  const anchor = annotation.viewer_anchor || {};
  if (![anchor.x, anchor.y, anchor.z].every(Number.isFinite)) return;
  const geometry = new THREE.SphereGeometry(markerRadius(), 20, 12);
  const material = new THREE.MeshStandardMaterial({
    color: annotation.status === "resolved" ? 0x10b981 : 0xf59e0b,
    emissive: annotation.status === "resolved" ? 0x064e3b : 0x78350f,
  });
  const marker = new THREE.Mesh(geometry, material);
  marker.position.set(anchor.x, anchor.y, anchor.z);
  marker.userData.annotation = annotation;
  annotationMarkers.add(marker);
}

async function loadViewerAnnotations() {
  clearAnnotationMarkers();
  if (!annotationsUrl) return;
  try {
    const payload = await fetchJson(annotationsUrl);
    (payload.annotations || []).forEach(addAnnotationMarker);
  } catch (error) {
    setStatus(error.message || "3D-Anmerkungen konnten nicht geladen werden.");
  }
}

function vectorPayload(vector) {
  return { x: vector.x, y: vector.y, z: vector.z };
}

function cancelAnnotation() {
  annotationMode = false;
  pendingAnchor = null;
  pendingCamera = null;
  annotateButton?.classList.remove("btn-primary");
  if (annotationForm) annotationForm.hidden = true;
  if (annotationText) annotationText.value = "";
}

annotateButton?.addEventListener("click", () => {
  annotationMode = !annotationMode;
  pendingAnchor = null;
  pendingCamera = null;
  annotationForm.hidden = true;
  annotateButton.classList.toggle("btn-primary", annotationMode);
  setStatus(
    annotationMode ? "Punkt am Modell anklicken." : "",
    annotationMode,
  );
});

rendererCanvasClickSetup();

function rendererCanvasClickSetup() {
  canvasHost.addEventListener("click", (event) => {
    if (!renderer || !currentObject) return;
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(pointer, camera);

    if (!annotationMode) {
      const markerHit = raycaster.intersectObjects(
        annotationMarkers.children,
        true,
      )[0];
      const annotation = markerHit?.object?.userData?.annotation;
      if (annotation) {
        setStatus(
          `${annotation.status === "resolved" ? "Erledigt" : "Offen"}: ${annotation.text}`,
        );
      }
      return;
    }

    const hit = raycaster.intersectObject(currentObject, true)[0];
    if (!hit) {
      setStatus("Kein Modellpunkt getroffen. Bitte erneut klicken.");
      return;
    }
    pendingAnchor = vectorPayload(hit.point);
    pendingCamera = {
      position: vectorPayload(camera.position),
      target: vectorPayload(controls.target),
    };
    annotationForm.hidden = false;
    annotationText.focus();
    setStatus("Punkt gewählt. Anmerkung eingeben.");
  });
}

annotationCancel?.addEventListener("click", cancelAnnotation);

annotationForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = annotationText.value.trim();
  if (!text || !pendingAnchor || !annotationsUrl) return;
  try {
    const payload = await fetchJson(annotationsUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        viewer_anchor: pendingAnchor,
        viewer_camera: pendingCamera,
      }),
    });
    addAnnotationMarker(payload.annotation);
    cancelAnnotation();
    setStatus("3D-Anmerkung gespeichert.");
  } catch (error) {
    setStatus(error.message || "3D-Anmerkung konnte nicht gespeichert werden.");
  }
});

async function loadModelBuffer(trigger, sourceUrl, loadId) {
  try {
    return await fetchModel(sourceUrl);
  } catch (error) {
    const prepareUrl = trigger.dataset.modelViewerPrepare;
    const statusUrl = trigger.dataset.modelViewerStatus;
    if (error.status !== 404 || !prepareUrl || !statusUrl) {
      throw error;
    }
    return prepareAndLoadModel(sourceUrl, prepareUrl, statusUrl, loadId);
  }
}

async function prepareAndLoadModel(sourceUrl, prepareUrl, statusUrl, loadId) {
  setStatus("3D-Vorschau wird erzeugt...");
  const initial = await fetchJson(prepareUrl, { method: "POST" });
  if (loadId !== activeLoadId) throw new Error("3D-Anzeige wurde abgebrochen.");
  if (initial.message) setStatus(initial.message);

  for (let attempt = 0; attempt < 120; attempt += 1) {
    const status = attempt === 0 ? initial : await fetchJson(statusUrl);
    if (loadId !== activeLoadId) throw new Error("3D-Anzeige wurde abgebrochen.");

    if (status.status === "ready") {
      setStatus("3D-Vorschau ist bereit. Modell wird geladen...");
      return fetchModel(status.source_url || sourceUrl);
    }

    if (status.status === "failed") {
      throw new Error(status.message || "3D-Vorschau konnte nicht erzeugt werden.");
    }

    setStatus(status.message || "3D-Vorschau wird erzeugt...");
    await wait(1500);
  }

  throw new Error("3D-Vorschau ist noch nicht fertig. Bitte spaeter erneut oeffnen.");
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
