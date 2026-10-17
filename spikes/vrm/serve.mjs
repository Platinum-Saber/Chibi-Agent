// Static server for the VRM viewer spike.
//   /            -> this folder (viewer, node_modules)
//   /models/...  -> D:\Projects\Chibi-Agent-Project\ChibiAgent\3d\ (samples, export); art stays out of git
//   POST /shot?name=x  -> saves the PNG body as 3d/shots/x.png (screenshots for docs/spikes.md)
// Usage: node serve.mjs [port]
import { createReadStream, mkdirSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = fileURLToPath(new URL(".", import.meta.url));
const MODELS = process.env.CHIBI_3D_DIR ?? "D:\\Projects\\Chibi-Agent-Project\\ChibiAgent\\3d";
const PORT = Number(process.argv[2] ?? 5179);
const TYPES = {
  ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json",
  ".vrm": "model/gltf-binary", ".glb": "model/gltf-binary", ".vrma": "model/gltf-binary",
  ".png": "image/png", ".jpg": "image/jpeg", ".css": "text/css",
};

function inside(root, rel) {
  const p = resolve(root, normalize(rel).replace(/^([/\\])+/, ""));
  return p === resolve(root) || p.startsWith(resolve(root) + sep) ? p : null;
}

createServer((req, res) => {
  const u = new URL(req.url, "http://x"), url = decodeURIComponent(u.pathname);
  if (req.method === "POST" && url === "/shot") {
    const name = (u.searchParams.get("name") ?? "shot").replace(/[^\w-]/g, "_");
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      mkdirSync(join(MODELS, "shots"), { recursive: true });
      writeFileSync(join(MODELS, "shots", name + ".png"), Buffer.concat(chunks));
      res.writeHead(200).end("saved");
    });
    return;
  }
  const path = url.startsWith("/models/") ? inside(MODELS, url.slice(8))
    : inside(HERE, url === "/" ? "viewer.html" : url);
  let st;
  try { st = path && statSync(path); } catch { st = null; }
  if (!st || !st.isFile()) { res.writeHead(404).end("not found"); return; }
  res.writeHead(200, { "Content-Type": TYPES[extname(path)] ?? "application/octet-stream", "Cache-Control": "no-store" });
  createReadStream(path).pipe(res);
}).listen(PORT, "127.0.0.1", () => console.log(`VRM viewer on http://127.0.0.1:${PORT}/  (models from ${MODELS})`));
