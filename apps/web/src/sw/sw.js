/* OZL 서비스 워커(설계 4-18). src/pages/sw.js.ts 가 기준 경로, 빌드 식별자, 저장 수를 채워 <기준>sw.js 로 낸다.
 *
 * 저장 규칙(보수적으로):
 * - 화면 틀(CSS, 글꼴, 스크립트, 아이콘)은 캐시 우선.
 * - 문서(HTML)와 자료(JSON)는 네트워크 우선. 연결이 없을 때만 저장분을 보여 주고, 그때 화면 맨 위에 띠를 단다.
 * - 저장하는 문서는 이슈 화면(최신판, 카드, 고정판)뿐이다. 첫 화면, 날짜 쪽, 키워드 쪽, 검색은 저장하지 않는다
 *   (내린 이슈의 제목이 그런 쪽에 남지 않게). 최근에 본 이슈 KEEP 건까지만 둔다.
 * - 연결될 때마다 offline.json(지금 살아 있는 판과 내림 목록)을 받아, 목록에 없는 이슈와 판, 판이 바뀐 최신판의
 *   저장분을 지운다. 캐시 이름에 빌드 식별자를 넣어 새 빌드가 오면 옛 캐시를 통째로 버린다.
 */
const BASE = "__BASE__";
const BUILD = "__BUILD__";
const KEEP = __KEEP__;
const SHELL = "ozl-shell-" + BUILD;
const DOCS = "ozl-docs-" + BUILD;
const OFFLINE = BASE + "offline/";
const LIST = BASE + "offline.json";
const INDEX_KEY = BASE + "__ozl-saved__";
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const ISSUE_RE = new RegExp("^" + esc(BASE) + "i/([a-z0-9]+(?:-[a-z0-9]+)*)/(?:(cards)/|r/(\\d+)/)?$");
const SHELL_RE = /\.(?:css|js|mjs|woff2?|svg|png|webmanifest)$/;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll([OFFLINE, BASE + "fonts/pretendard.css"])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith("ozl-") && k !== SHELL && k !== DOCS) await caches.delete(k);
    await self.clients.claim();
    await sync();
  })());
});

self.addEventListener("message", (e) => {
  const port = e.ports && e.ports[0];
  const reply = (v) => port && port.postMessage(v);
  if (e.data && e.data.type === "sync") e.waitUntil(sync().then(reply, (err) => reply({ ok: false, error: String(err) })));
  else if (e.data && e.data.type === "saved") e.waitUntil(readIndex().then((idx) => reply({ build: BUILD, saved: idx })));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith(BASE)) return;
  if (url.pathname === BASE + "sw.js") return;
  if (url.pathname.endsWith(".json") || url.pathname.startsWith(BASE + "pagefind/")) return; // 자료: 네트워크만(저장하지 않는다)
  const html = req.mode === "navigate" || (req.headers.get("accept") || "").includes("text/html");
  if (html) e.respondWith(doc(req, url));
  else if (SHELL_RE.test(url.pathname)) e.respondWith(shell(req));
});

async function shell(req) {
  const c = await caches.open(SHELL);
  const hit = await c.match(req, { ignoreSearch: true });
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok && res.type === "basic") c.put(req, res.clone());
  return res;
}

let lastSync = 0;
async function doc(req, url) {
  const m = url.pathname.match(ISSUE_RE);
  const key = url.origin + url.pathname;
  let res;
  try {
    res = await fetch(req);
  } catch (err) {
    const hit = m ? await (await caches.open(DOCS)).match(key) : null;
    if (hit) return withBand(hit);
    const off = await caches.match(OFFLINE);
    return off || new Response("연결이 없다.", { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } });
  }
  if (m) {
    if (res.ok && res.type === "basic") await save(key, res.clone(), m[1], !m[2] && !m[3]);
    else if (res.status === 404 || res.status === 410) await drop([key]);
  }
  if (Date.now() - lastSync > 60000) sync();
  return res;
}

// ---- 저장 목록(최근 본 순서) ----
let lock = Promise.resolve();
const serial = (fn) => (lock = lock.then(fn, fn));

async function readIndex() {
  const r = await (await caches.open(DOCS)).match(self.location.origin + INDEX_KEY);
  if (!r) return [];
  try { return await r.json(); } catch { return []; }
}
async function writeIndex(idx) {
  await (await caches.open(DOCS)).put(self.location.origin + INDEX_KEY, new Response(JSON.stringify(idx), { headers: { "content-type": "application/json" } }));
}

const ENT = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&#x27;": "'" };
const unent = (s) => s.replace(/&(?:amp|lt|gt|quot|#39|#x27);/g, (x) => ENT[x]);

function save(key, res, slug, latest) {
  return serial(async () => {
    const text = await res.text();
    const rev = (text.match(/<meta name="ozl-rev" content="(\d+)"/) || [])[1] || "";
    const title = unent(((text.match(/<title>([^<]*)<\/title>/) || [])[1] || "").replace(/ · (\d+판 · )?(카드 · )?OZL$/, "").replace(/ · \d+판$/, ""));
    const at = new Date().toISOString();
    const headers = new Headers(res.headers);
    headers.set("x-ozl-saved-at", at);
    headers.set("x-ozl-rev", rev);
    headers.set("content-type", "text/html; charset=utf-8");
    const cache = await caches.open(DOCS);
    await cache.put(key, new Response(text, { status: 200, headers }));
    let idx = await readIndex();
    const old = idx.find((x) => x.slug === slug);
    const entry = { slug, title: latest && title ? title : (old && old.title) || title, rev: latest ? rev : (old && old.rev) || rev, at, pages: [...new Set([key, ...((old && old.pages) || [])])] };
    idx = [entry, ...idx.filter((x) => x.slug !== slug)];
    for (const gone of idx.slice(KEEP)) for (const p of gone.pages) await cache.delete(p);
    await writeIndex(idx.slice(0, KEEP));
  });
}

function drop(keys) {
  return serial(async () => {
    const cache = await caches.open(DOCS);
    for (const k of keys) await cache.delete(k);
    const idx = (await readIndex()).map((x) => ({ ...x, pages: x.pages.filter((p) => !keys.includes(p)) })).filter((x) => x.pages.length);
    await writeIndex(idx);
  });
}

// ---- 연결될 때: 지금 살아 있는 판과 대조해 지운다 ----
async function sync() {
  let list;
  try {
    const r = await fetch(LIST, { cache: "no-store" });
    if (!r.ok) return { ok: false, status: r.status };
    list = await r.json();
  } catch {
    return { ok: false, offline: true };
  }
  lastSync = Date.now();
  const cache = await caches.open(DOCS);
  const gone = [];
  for (const req of await cache.keys()) {
    const p = new URL(req.url).pathname;
    const m = p.match(ISSUE_RE);
    if (!m) continue;
    const live = list.issues && list.issues[m[1]];
    let out = !live;
    if (!out && m[3]) {
      const r = Number(m[3]);
      out = !live.revs.includes(r) || (list.takedowns || []).some((t) => t.slug === m[1] && t.rev === r);
    } else if (!out) {
      const hit = await cache.match(req);
      out = String(live.rev ?? "") !== ((hit && hit.headers.get("x-ozl-rev")) || "");
    }
    if (out) gone.push(req.url);
  }
  if (gone.length) await drop(gone);
  if (list.build && list.build !== BUILD) self.registration.update().catch(() => {});
  return { ok: true, build: list.build, removed: gone.map((u) => new URL(u).pathname) };
}

// ---- 연결 없이 보여 줄 때의 띠 ----
function when(iso) {
  try {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
    return `${parts.month}월 ${parts.day}일 ${parts.hour}:${parts.minute}`;
  } catch {
    return "";
  }
}
async function withBand(res) {
  const text = await res.text();
  const at = when(res.headers.get("x-ozl-saved-at"));
  const band = `<div class="offline-band" role="status" data-offline-band>연결이 없어 저장된 판을 보여 준다(저장 시각 ${at})</div>`;
  const out = text.replace(/<body([^>]*)>/, (b) => b + band);
  return new Response(out, { status: 200, headers: { "content-type": "text/html; charset=utf-8", "x-ozl-offline": "1" } });
}
