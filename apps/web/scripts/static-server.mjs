// 빌드 결과 폴더를 127.0.0.1 에 띄우는 작은 정적 서버(cards.mjs, checks/offline.mjs 가 쓴다).
// root 는 함수로 받아 요청마다 읽는다 — 점검 중에 결과 폴더를 바꿔 끼울 수 있게.
// port 0 이면 운영체제가 빈 포트를 준다(4321 과 겹치지 않는다).
import fs from "node:fs";
import http from "node:http";
import path from "node:path";

const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
  ".json": "application/json", ".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml",
  ".png": "image/png", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml", ".wasm": "application/wasm",
  ".webmanifest": "application/manifest+json",
};

export async function serve({ root, base = "/preview/", port = 0 }) {
  const getRoot = typeof root === "function" ? root : () => root;
  let offline = false;
  const server = http.createServer((req, res) => {
    if (offline) {
      // 연결 끊김 흉내는 브라우저 쪽(context.setOffline)에서 한다. 이 깃발은 남겨 둔 보조 수단이다.
      req.socket.destroy();
      return;
    }
    const dir = path.resolve(getRoot());
    let p;
    try { p = decodeURIComponent((req.url || "/").split("?")[0].split("#")[0]); } catch { p = ""; }
    let f = null;
    if (p.startsWith(base)) {
      f = path.join(dir, p.slice(base.length));
      if (!f.startsWith(dir)) f = null;
      else if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
      if (f && !(fs.existsSync(f) && fs.statSync(f).isFile())) f = null;
    }
    if (!f) {
      const nf = path.join(dir, "404.html");
      res.writeHead(404, { "content-type": TYPES[".html"], "cache-control": "no-store" });
      res.end(fs.existsSync(nf) ? fs.readFileSync(nf) : "not found");
      return;
    }
    const headers = { "content-type": TYPES[path.extname(f)] || "application/octet-stream", "cache-control": "no-store" };
    if (f.endsWith("sw.js")) headers["service-worker-allowed"] = base;
    res.writeHead(200, headers);
    fs.createReadStream(f).pipe(res);
  });
  await new Promise((ok) => server.listen(port, "127.0.0.1", ok));
  const origin = `http://127.0.0.1:${server.address().port}`;
  return {
    origin,
    url: (rel = "") => origin + base + encodeURI(rel),
    setOffline: (v) => { offline = v; },
    close: () => new Promise((ok) => { server.closeAllConnections?.(); server.close(() => ok()); }),
  };
}
