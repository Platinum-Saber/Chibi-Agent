// VRM viewer spike: load a model, idle it (breath, blink, gaze), try expressions and
// a fake lip sync, and show the frame rate.
// Query: ?model=samples/VRM1_Constraint_Twist_Sample.vrm  (path under D:\Projects\Chibi-Agent-Project\ChibiAgent\3d)
//        &bg=transparent  (no background or HUD, as in the overlay)
//        &cam=face|bust|full  (starting framing; full is the default)
// Keys: 1-9 her expressions, 0 neutral, g halo glow, e eye glow, m toggle mouth (lip-sync test),
//       r reset camera.
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

const q = new URLSearchParams(location.search);
const MODEL = q.get("model") ?? "samples/VRM1_Constraint_Twist_Sample.vrm";
const transparent = q.get("bg") === "transparent";
if (transparent) document.body.classList.add("transparent");
// Her 9 expressions (spikes/vrm/blender/s5_expressions.py); "upset" is the VRM preset sad.
// Models without the custom ones (the plain samples) just ignore those names.
const KEYS = { 1: "neutral", 2: "happy", 3: "surprised", 4: "pout", 5: "sad", 6: "sleepy", 7: "thinking", 8: "focused", 9: "warning" };
const GLOW = { g: "ringGlow", e: "eyeGlow" };
const glow = new Set();

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(devicePixelRatio);
renderer.setSize(innerWidth, innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, innerWidth / innerHeight, 0.1, 20);
const controls = new OrbitControls(camera, renderer.domElement);
let camScale = 1; // set from the model height, so the chibi frames the same way
const CAMS = { full: [1.35, 2.2, 1.25], bust: [1.4, 1.3, 1.3], face: [1.42, 0.75, 1.4] };
function resetCamera() {
  const [y, z, ty] = CAMS[q.get("cam")] ?? CAMS.full;
  camera.position.set(0, y * camScale, z * camScale);
  controls.target.set(0, ty * camScale, 0);
  controls.update();
}
resetCamera();
const light = new THREE.DirectionalLight(0xffffff, Math.PI);
light.position.set(1, 1, 1).normalize();
scene.add(light, new THREE.AmbientLight(0xffffff, 0.4));

const gazeTarget = new THREE.Object3D();
camera.add(gazeTarget);
scene.add(camera);
addEventListener("pointermove", (e) => {
  gazeTarget.position.set((e.clientX / innerWidth - 0.5) * 2, -(e.clientY / innerHeight - 0.5) * 2, -2);
});

const thinkTarget = new THREE.Object3D();
thinkTarget.position.set(-0.6, 1.0, -2);
camera.add(thinkTarget);
const hud = document.getElementById("hud");
let vrm = null, expr = "neutral", mouth = false;
window.spike = {
  camera, controls, scene, renderer, get vrm() { return vrm; }, setExpr: (n) => { expr = n; }, glow, dts: [], noBlink: false,
  gpu: (() => {
    const gl = renderer.getContext(), ext = gl.getExtension("WEBGL_debug_renderer_info");
    return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
  })(),
  // render one frame and POST it to the server, which saves it under 3d/shots/
  shot: (name) => new Promise((ok) => {
    frame(); // a full update, so it works while the page is hidden and rAF is paused
    renderer.domElement.toBlob((b) => fetch(`/shot?name=${name}`, { method: "POST", body: b }).then(ok));
  }),
};

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));
loader.load(`/models/${MODEL}`, (gltf) => {
  vrm = gltf.userData.vrm;
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  VRMUtils.combineSkeletons(gltf.scene);
  VRMUtils.rotateVRM0(vrm); // VRM 0.x faces -Z; no-op for 1.0
  vrm.scene.traverse((o) => { o.frustumCulled = false; });
  if (vrm.lookAt) vrm.lookAt.target = gazeTarget;
  // arms down from the T-pose
  const h = vrm.humanoid;
  h.getNormalizedBoneNode("leftUpperArm").rotation.z = -1.2;
  h.getNormalizedBoneNode("rightUpperArm").rotation.z = 1.2;
  scene.add(vrm.scene);
  const headY = h.getNormalizedBoneNode("head").getWorldPosition(new THREE.Vector3()).y;
  camScale = headY / 1.33; // 1.33 m: head bone height of the pixiv base
  resetCamera();
}, undefined, (err) => { hud.textContent = `failed to load ${MODEL}\n${err}`; console.error(err); });

addEventListener("keydown", (e) => {
  if (!vrm) return;
  if (e.key === "r") resetCamera();
  if (e.key === "m") mouth = !mouth;
  if (GLOW[e.key]) glow.has(GLOW[e.key]) ? glow.delete(GLOW[e.key]) : glow.add(GLOW[e.key]);
  const name = e.key === "0" ? "neutral" : KEYS[e.key];
  if (name) expr = name;
});
addEventListener("resize", () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});

const clock = new THREE.Clock();
let frames = 0, fpsT = 0, fps = 0, nextBlink = 2;
function frame() {
  const raw = clock.getDelta(), dt = Math.min(raw, 0.05), t = clock.elapsedTime; // clamp: no spring-bone jumps after a pause
  frames++; fpsT += dt;
  spike.dts.push(raw * 1000); // frame times in ms, drained by fps_qt.py
  if (fpsT >= 1) { fps = frames / fpsT; frames = 0; fpsT = 0; }
  if (vrm) {
    const em = vrm.expressionManager;
    for (const n of Object.values(KEYS)) em.setValue(n, n === expr ? 1 : 0);
    for (const n of Object.values(GLOW)) em.setValue(n, glow.has(n) ? 1 : 0);
    // thinking: eyes drift up and aside
    if (vrm.lookAt) vrm.lookAt.target = expr === "thinking" ? thinkTarget : gazeTarget;
    // blink every 2-6 s unless an expression closes the eyes already
    const sinceBlink = t - nextBlink;
    if (sinceBlink > 0.15) nextBlink = t + 2 + Math.random() * 4;
    if (expr !== "blink") em.setValue("blink", sinceBlink > 0 && !spike.noBlink ? Math.sin((sinceBlink / 0.15) * Math.PI) : 0);
    em.setValue("aa", mouth ? 0.5 + 0.5 * Math.sin(t * 18) * Math.sin(t * 5) : 0);
    vrm.humanoid.getNormalizedBoneNode("chest").rotation.x = 0.02 * Math.sin(t * 2.2); // breath
    vrm.update(dt);
  }
  renderer.render(scene, camera);
  if (!transparent) {
    hud.textContent = `${MODEL}\n${fps.toFixed(0)} fps · ${renderer.info.render.triangles} tris\n` +
      `expression: ${expr}${[...glow].map((g) => " · " + g).join("")}${mouth ? " · mouth" : ""}\n` +
      `1 neutral 2 happy 3 surprised 4 pout 5 upset 6 sleepy 7 thinking 8 focused 9 warning\n` +
      `g halo glow · e eye glow · m mouth · r camera`;
  }
}
renderer.setAnimationLoop(frame);
