// 화면 점검(설계 8절). 미리보기 빌드를 127.0.0.1 의 빈 포트에 띄워 찍고 잰 뒤 서버를 내린다.
//
// 쓰는 법(apps/web 에서):
//   PLAYWRIGHT_BROWSERS_PATH=$PWD/.pw-browsers node checks/visual.mjs            # 임시 폴더에 미리보기 빌드 후 점검
//   PLAYWRIGHT_BROWSERS_PATH=$PWD/.pw-browsers node checks/visual.mjs --out <폴더> # 이미 만든 결과를 점검
// 결과: <저장소>/private/out/screens/web_<YYYYMMDD_HHMMSS>/ (result.json + PNG)
// 종료 코드: 기준을 모두 넘으면 0, 하나라도 못 미치면 1, 점검 자체가 실패하면 2.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "../..");
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(WEB_ROOT, ".pw-browsers");
const { chromium } = await import("playwright");
const { default: AxeBuilder } = await import("@axe-core/playwright");

const BASE = "/preview/";
const PAGES = [
  ["home", ""],
  ["issue", "i/hanbit-bus-fare-400/"],
  ["revision", "i/hanbit-bus-fare-400/r/2/"],
  ["day", "d/2099-01-02/"],
  ["keyword", "k/버스-요금/"],
  ["about", "about/"],
  ["cards", "i/hanbit-bus-fare-400/cards/"],
];
const WIDTHS = [360, 390, 768, 1280];
const HEIGHT = 800;
// 설계 5-3 의 시험 질의 10개와 기대 이슈(주소의 slug 로 맞춘다).
const QUERIES = [
  ["한빛시가", "hanbit-bus-fare-400"],
  ["버스요금", "hanbit-bus-fare-400"],
  ["요금을 올린", "hanbit-bus-fare-400"],
  ["누리전자의", "nuri-battery-recall"],
  ["보조배터리", "nuri-battery-recall"],
  ["리콜", "nuri-battery-recall"],
  ["적자 200억", "hanbit-bus-fare-400"],
  ["가람군 저수지", "garam-reservoir-levee"],
  ["저수지에서", "garam-reservoir-levee"],
  ["도서관", "daon-library-hours"],
];

function stamp() {
  const kst = new Date(Date.now() + 9 * 3600 * 1000).toISOString();
  return kst.slice(0, 19).replace(/[-:]/g, "").replace("T", "_");
}

function argValue(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

// ---- 빌드 ----
let outDir = argValue("--out");
let tmpBuild = null;
if (!outDir) {
  tmpBuild = fs.mkdtempSync(path.join(os.tmpdir(), "ozl-web-visual-"));
  const r = spawnSync("npm", ["run", "build:preview"], {
    cwd: WEB_ROOT,
    env: { ...process.env, OZL_WEB_OUT: tmpBuild },
    encoding: "utf-8",
  });
  if (r.status !== 0) {
    console.error(r.stdout, r.stderr);
    console.error(`[visual] 미리보기 빌드 실패(코드 ${r.status})`);
    process.exit(2);
  }
  outDir = tmpBuild;
}
outDir = path.resolve(outDir);

// ---- 정적 서버(127.0.0.1, 빈 포트) ----
const TYPES = {
  ".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "text/javascript", ".mjs": "text/javascript",
  ".json": "application/json", ".woff2": "font/woff2", ".woff": "font/woff", ".svg": "image/svg+xml",
  ".png": "image/png", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml", ".wasm": "application/wasm",
  ".pf_meta": "application/octet-stream", ".pf_index": "application/octet-stream", ".pf_fragment": "application/octet-stream",
  ".pf_filter": "application/octet-stream",
};
function resolveFile(urlPath) {
  let p;
  try { p = decodeURIComponent(urlPath.split("?")[0].split("#")[0]); } catch { return null; }
  if (!p.startsWith(BASE)) return null;
  const rel = p.slice(BASE.length);
  let f = path.join(outDir, rel);
  if (!f.startsWith(outDir)) return null;
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
  return fs.existsSync(f) && fs.statSync(f).isFile() ? f : null;
}
const server = http.createServer((req, res) => {
  const f = resolveFile(req.url || "/");
  if (!f) {
    const nf = path.join(outDir, "404.html");
    res.writeHead(404, { "content-type": TYPES[".html"] });
    res.end(fs.existsSync(nf) ? fs.readFileSync(nf) : "not found");
    return;
  }
  res.writeHead(200, { "content-type": TYPES[path.extname(f)] || "application/octet-stream", "cache-control": "no-store" });
  fs.createReadStream(f).pipe(res);
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const ORIGIN = `http://127.0.0.1:${server.address().port}`;
const at = (p) => ORIGIN + BASE + encodeURI(p);

const shotDir = path.join(REPO_ROOT, "private/out/screens", `web_${stamp()}`);
fs.mkdirSync(shotDir, { recursive: true });

const result = {
  made_at: new Date().toISOString(),
  build: outDir,
  origin: ORIGIN,
  screenshots: [],
  overflow: [],
  axe: { light: [], dark: [] },
  zoom: [],
  keyboard: null,
  slow: [],
  links: null,
  search: null,
  title60: null,
  reduced_motion: null,
};

// 글자를 가진 요소 가운데 잘린 것(overflow 가 visible 이 아니고 내용이 넘침).
const CLIP_FN = () => {
  const out = [];
  for (const el of document.querySelectorAll("body *")) {
    const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!hasText) continue;
    const cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    if (el.closest(".skip-link, [class*=skip]") && r.top < 0) continue;
    // 화면 읽기 전용·색인 전용(1px 상자 + clip)은 일부러 숨긴 것이라 잘림으로 세지 않는다.
    const hiddenBox = (e) => { const c = getComputedStyle(e); const b = e.getBoundingClientRect(); return (b.width <= 1 && b.height <= 1) || (c.clipPath && c.clipPath.startsWith("inset(50%")) || (c.clip && c.clip.startsWith("rect(0")); };
    let anc = el, skip = false;
    while (anc && anc !== document.body) { if (hiddenBox(anc)) { skip = true; break; } anc = anc.parentElement; }
    if (skip) continue;
    const clipX = cs.overflowX !== "visible" && el.scrollWidth > el.clientWidth + 1;
    const clipY = cs.overflowY !== "visible" && el.scrollHeight > el.clientHeight + 1;
    const ell = cs.textOverflow === "ellipsis" || (cs.webkitLineClamp && cs.webkitLineClamp !== "none");
    // 화면 밖으로 나간 글자(오른쪽 끝 넘김)
    const offRight = r.right > document.documentElement.clientWidth + 1 && cs.position !== "absolute";
    if (clipX || clipY || ell || offRight) {
      out.push({
        sel: el.tagName.toLowerCase() + (el.id ? "#" + el.id : "") + (el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/).join(".") : ""),
        text: el.textContent.trim().slice(0, 40),
        why: [clipX && "가로 잘림", clipY && "세로 잘림", ell && "말줄임", offRight && "화면 밖"].filter(Boolean).join(","),
      });
    }
  }
  return out;
};
const OVERFLOW_FN = () => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth });

function axeSummary(r) {
  return r.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    count: v.nodes.length,
    nodes: v.nodes.slice(0, 5).map((n) => ({ target: n.target.join(" "), summary: (n.failureSummary || "").split("\n").slice(1, 3).join(" ").slice(0, 200) })),
  }));
}

const browser = await chromium.launch();
try {
  // ---- 1. 스크린샷 · 가로 스크롤 · axe(밝은 화면) ----
  for (const w of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width: w, height: HEIGHT }, colorScheme: "light" });
    const page = await ctx.newPage();
    for (const [name, p] of PAGES) {
      const resp = await page.goto(at(p), { waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts && document.fonts.ready);
      const file = `${name}_${w}.png`;
      await page.screenshot({ path: path.join(shotDir, file), fullPage: true });
      result.screenshots.push(file);
      const o = await page.evaluate(OVERFLOW_FN);
      result.overflow.push({ page: name, width: w, status: resp?.status(), ...o, ok: o.scrollWidth <= o.innerWidth });
      const a = await new AxeBuilder({ page }).analyze();
      result.axe.light.push({ page: name, width: w, violations: axeSummary(a) });
    }
    await ctx.close();
  }

  // ---- 2. 어두운 화면 ----
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: HEIGHT }, colorScheme: "dark" });
    const page = await ctx.newPage();
    for (const [name, p] of PAGES) {
      await page.goto(at(p), { waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts && document.fonts.ready);
      if (name === "home" || name === "issue") {
        const file = `${name}_390_dark.png`;
        await page.screenshot({ path: path.join(shotDir, file), fullPage: true });
        result.screenshots.push(file);
        const o = await page.evaluate(OVERFLOW_FN);
        result.overflow.push({ page: name, width: 390, dark: true, ...o, ok: o.scrollWidth <= o.innerWidth });
      }
      const a = await new AxeBuilder({ page }).analyze();
      result.axe.dark.push({ page: name, width: 390, violations: axeSummary(a) });
    }
    await ctx.close();
  }

  // ---- 3. 200% 확대 ----
  // (가) 글자 200%: 폭 390 에서 뿌리 글자 크기를 200% 로. (나) 쪽 200%: 390 을 두 배로 키운 것 = CSS 폭 195.
  for (const [mode, width] of [["text200", 390], ["page200", 195]]) {
    const ctx = await browser.newContext({ viewport: { width, height: HEIGHT }, deviceScaleFactor: mode === "page200" ? 2 : 1 });
    const page = await ctx.newPage();
    for (const [name, p] of PAGES.filter(([n]) => n === "home" || n === "issue")) {
      await page.goto(at(p), { waitUntil: "networkidle" });
      if (mode === "text200") await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
      await page.waitForTimeout(100);
      const o = await page.evaluate(OVERFLOW_FN);
      const clipped = await page.evaluate(CLIP_FN);
      const file = `${name}_390_${mode}.png`;
      await page.screenshot({ path: path.join(shotDir, file), fullPage: true });
      result.screenshots.push(file);
      result.zoom.push({ page: name, mode, width, ...o, overflow_ok: o.scrollWidth <= o.innerWidth, clipped, ok: o.scrollWidth <= o.innerWidth && clipped.length === 0 });
    }
    await ctx.close();
  }

  // ---- 4. 키보드(이슈 화면, 폭 390) ----
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: HEIGHT } });
    const page = await ctx.newPage();
    await page.goto(at("i/hanbit-bus-fare-400/"), { waitUntil: "networkidle" });
    const total = await page.evaluate(() => {
      const els = [...document.querySelectorAll("a[href], button, summary, input, select, textarea")];
      let i = 0;
      const vis = [];
      for (const el of els) {
        el.dataset.kbId = String(i++);
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        // 접힌 <details> 안의 것은 펼치기 전에는 닿을 수 없으므로 뺀다(summary 는 센다).
        const inClosed = el.closest("details:not([open])") && el.tagName !== "SUMMARY" && !el.closest("summary");
        const hidden = el.closest("[hidden]") || cs.visibility === "hidden" || cs.display === "none" || (r.width === 0 && r.height === 0 && !el.matches(".skip-link, [class*=skip]"));
        if (!inClosed && !hidden && !el.disabled) vis.push({ id: el.dataset.kbId, tag: el.tagName.toLowerCase(), text: (el.textContent || el.getAttribute("aria-label") || el.value || "").trim().slice(0, 30), href: el.getAttribute("href") });
      }
      return vis;
    });
    const reached = new Map();
    let firstTab = null;
    for (let i = 0; i < 400; i++) {
      await page.keyboard.press("Tab");
      const info = await page.evaluate(() => {
        const el = document.activeElement;
        if (!el || el === document.body) return null;
        const cs = getComputedStyle(el);
        const r = el.getBoundingClientRect();
        return {
          id: el.dataset.kbId ?? null,
          tag: el.tagName.toLowerCase(),
          text: (el.textContent || "").trim().slice(0, 30),
          outline: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}`,
          visible: (cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== "none"),
          onScreen: r.width > 0 && r.height > 0,
        };
      });
      if (!info) continue;
      if (i === 0) firstTab = info.text;
      const key = info.id ?? `${info.tag}:${info.text}`;
      if (reached.has(key)) break; // 한 바퀴 돌았다
      reached.set(key, info);
    }
    const missing = total.filter((t) => !reached.has(t.id));
    const noFocusRing = [...reached.values()].filter((r) => !r.visible || !r.onScreen);
    result.keyboard = {
      page: "issue", width: 390, total: total.length, reached: total.length - missing.length,
      first_tab: firstTab, missing, no_focus_ring: noFocusRing,
      ok: missing.length === 0 && noFocusRing.length === 0,
    };
    // 초점 표시를 눈으로 보려고, 본문 첫 링크에 초점을 둔 모습을 한 장 남긴다.
    await page.evaluate(() => document.querySelector("main a[href]")?.focus());
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await page.screenshot({ path: path.join(shotDir, "issue_390_focus.png") });
    result.screenshots.push("issue_390_focus.png");
    await ctx.close();
  }

  // ---- 5. 느린 연결(느린 3G: 400kbps / 400kbps / 지연 400ms, 캐시 끔) ----
  for (const [name, p] of PAGES.filter(([n]) => n === "home" || n === "issue")) {
    const ctx = await browser.newContext({ viewport: { width: 390, height: HEIGHT } });
    const page = await ctx.newPage();
    const cdp = await ctx.newCDPSession(page);
    await cdp.send("Network.enable");
    await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
    await cdp.send("Network.emulateNetworkConditions", {
      offline: false, latency: 400, downloadThroughput: (400 * 1000) / 8, uploadThroughput: (400 * 1000) / 8,
    });
    // 첫 글이 "보이는" 시각 = 브라우저가 글을 처음 그린 시각(first-contentful-paint, 탐색 시작 기준).
    // HTML 에 글이 들어왔어도 막는 CSS(글꼴 CSS 포함)를 다 받기 전에는 그려지지 않는다.
    await page.addInitScript(() => {
      window.__fcp = null;
      new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.name === "first-contentful-paint") window.__fcp = e.startTime; }).observe({ type: "paint", buffered: true });
    });
    const blocking = [];
    page.on("requestfinished", async (rq) => {
      const t = rq.timing();
      const sz = await rq.sizes().catch(() => null);
      blocking.push({ url: rq.url().replace(ORIGIN, ""), type: rq.resourceType(), ms: Math.round(t.responseEnd), bytes: sz?.responseBodySize });
    });
    await page.goto(at(p), { waitUntil: "commit" });
    const domText = await page.waitForFunction(() => {
      const m = document.querySelector("main");
      return m && m.textContent.trim() ? performance.now() : false;
    }, null, { timeout: 30000, polling: 20 }).then((h) => h.jsonValue());
    await page.waitForFunction(() => window.__fcp !== null, null, { timeout: 60000, polling: 50 });
    const fcp = await page.evaluate(() => window.__fcp);
    await page.waitForLoadState("load", { timeout: 120000 });
    const load = await page.evaluate(() => performance.getEntriesByType("navigation")[0]?.loadEventEnd ?? null);
    result.slow.push({
      page: name, first_text_paint_ms: Math.round(fcp), text_in_dom_ms: Math.round(domText), load_ms: load && Math.round(load),
      css_and_fonts: blocking.filter((b) => b.type === "stylesheet" || b.type === "font").slice(0, 8),
      ok: fcp <= 3000,
    });
    await ctx.close();
  }

  // ---- 6. 안쪽 링크 전부 따라가기 ----
  {
    const ctx = await browser.newContext();
    const req = ctx.request;
    const seen = new Map(); // 경로 → {status, html}
    const queue = [BASE];
    const broken = [];
    const fragChecks = [];
    let linksChecked = 0;
    const norm = (href, from) => {
      try { return new URL(href, ORIGIN + from); } catch { return null; }
    };
    while (queue.length) {
      const cur = queue.shift();
      if (seen.has(cur)) continue;
      const r = await req.get(ORIGIN + cur);
      const ct = r.headers()["content-type"] || "";
      const body = ct.includes("text/html") ? await r.text() : null;
      seen.set(cur, { status: r.status(), html: body });
      if (!body) continue;
      const attrs = [...body.matchAll(/\s(?:href|src)="([^"]+)"/g)].map((m) => m[1].replace(/&amp;/g, "&"));
      for (const a of attrs) {
        if (/^(mailto:|tel:|javascript:|data:)/.test(a)) continue;
        const u = norm(a, cur);
        if (!u || u.origin !== ORIGIN) continue;
        linksChecked++;
        const pathOnly = u.pathname;
        if (!pathOnly.startsWith(BASE)) { broken.push({ from: cur, href: a, why: "기준 밖" }); continue; }
        if (u.hash) fragChecks.push({ from: cur, path: pathOnly, id: decodeURIComponent(u.hash.slice(1)), href: a });
        if (!seen.has(pathOnly) && !queue.includes(pathOnly)) queue.push(pathOnly);
      }
    }
    for (const [p, v] of seen) {
      if (v.status !== 200) broken.push({ path: decodeURI(p), status: v.status });
    }
    for (const f of fragChecks) {
      const target = seen.get(f.path);
      if (!target?.html) continue;
      if (!f.id) continue;
      const esc = f.id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (!new RegExp(`\\sid="${esc}"`).test(target.html)) broken.push({ from: decodeURI(f.from), href: f.href, why: "쪽 안 조각 없음" });
    }
    const uniqBroken = [...new Map(broken.map((b) => [JSON.stringify(b), b])).values()];
    result.links = {
      pages_and_files: seen.size,
      html_pages: [...seen.values()].filter((v) => v.html).length,
      links_checked: linksChecked,
      broken: uniqBroken,
      ok: uniqBroken.length === 0,
    };
    await ctx.close();
  }

  // ---- 7. 검색 상자에 질의 10개 ----
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: HEIGHT } });
    const page = await ctx.newPage();
    const rows = [];
    for (const [q, slug] of QUERIES) {
      await page.goto(at("search/"), { waitUntil: "networkidle" });
      const input = page.locator("form.search-box input[name=q]");
      await input.fill(q);
      await input.press("Enter");
      let status = "";
      try {
        await page.waitForFunction(() => {
          const s = document.querySelector("[data-search-status]")?.textContent || "";
          return s && s !== "찾는 중";
        }, null, { timeout: 15000 });
        status = await page.locator("[data-search-status]").innerText();
      } catch {
        status = "(시간 초과)";
      }
      const hrefs = await page.$$eval("[data-search-results] li a", (as) => as.map((a) => a.getAttribute("href")));
      const titles = await page.$$eval("[data-search-results] li a", (as) => as.map((a) => a.textContent.trim()));
      const rank = hrefs.findIndex((h) => h && h.includes(`/i/${slug}/`));
      // 결과는 DOM 으로만 그린다: 허용한 요소(li, p, a, span, mark) 밖의 것이 없고, 링크는 모두 기준 경로 안이다.
      const tags = await page.$$eval("[data-search-results] *", (els) => [...new Set(els.map((e) => e.tagName.toLowerCase()))]);
      const domOk = tags.every((t) => ["li", "p", "a", "span", "mark"].includes(t)) && hrefs.every((h) => h && h.startsWith(BASE));
      rows.push({ q, expect: slug, status, results: hrefs.length, rank: rank >= 0 ? rank + 1 : null, top3: titles.slice(0, 3), tags, dom_ok: domOk, ok: rank >= 0 && rank < 3 && domOk });
    }
    await page.screenshot({ path: path.join(shotDir, "search_390_last.png"), fullPage: true });
    result.screenshots.push("search_390_last.png");
    const pass = rows.filter((r) => r.ok).length;
    result.search = { pass, total: rows.length, rows, ok: pass >= 9 };
    await ctx.close();
  }

  // ---- 8. 긴 제목(첫 화면 · 이슈 화면). 이슈 화면의 제목은 글(article)의 제목이다(명세 2절, 45자까지) ----
  {
    const iss = JSON.parse(fs.readFileSync(path.join(WEB_ROOT, "sample-data/issues/garam-reservoir-levee.json"), "utf-8"));
    const want = iss.article?.title || iss.title || "";
    const ctx = await browser.newContext({ viewport: { width: 390, height: HEIGHT } });
    const page = await ctx.newPage();
    await page.goto(at(""), { waitUntil: "networkidle" });
    const onHome = await page.$$eval('a[href*="garam-reservoir-levee"]', (as) => as.map((a) => a.textContent.replace(/\s+/g, " ").trim()));
    await page.goto(at("i/garam-reservoir-levee/"), { waitUntil: "networkidle" });
    const h1 = (await page.locator("h1").first().innerText()).replace(/\s+/g, " ").replace(/^예시\s*/, "").trim();
    const clipped = await page.evaluate(CLIP_FN);
    result.title60 = { want, chars: [...want].length, home_links: onHome, issue_h1: h1, home_ok: onHome.some((t) => t.includes(want)), issue_ok: h1 === want, clipped, ok: onHome.some((t) => t.includes(want)) && h1 === want && clipped.length === 0 };
    await ctx.close();
  }

  // ---- 9. 움직임 줄이기 ----
  {
    const ctx = await browser.newContext({ viewport: { width: 390, height: HEIGHT }, reducedMotion: "reduce" });
    const page = await ctx.newPage();
    const bad = [];
    for (const [name, p] of PAGES) {
      await page.goto(at(p), { waitUntil: "networkidle" });
      const b = await page.evaluate(() => {
        const out = [];
        for (const el of document.querySelectorAll("*")) {
          const cs = getComputedStyle(el);
          const td = cs.transitionDuration.split(",").some((d) => parseFloat(d) > 0);
          const ad = cs.animationDuration.split(",").some((d) => parseFloat(d) > 0);
          if (td || ad) out.push(el.tagName.toLowerCase() + (el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/).join(".") : ""));
        }
        return out.slice(0, 10);
      });
      if (b.length) bad.push({ page: name, els: b });
    }
    result.reduced_motion = { bad, ok: bad.length === 0 };
    await ctx.close();
  }
  // ---- 10. 넘겨 보는 카드(설계 4-17): 폭 넷에서 가로 스크롤 0, 키보드로 다음/이전, 스크립트 없이 세로로 읽힘 ----
  {
    const CARDS = "i/hanbit-bus-fare-400/cards/";
    const rows = [];
    for (const w of WIDTHS) {
      const ctx = await browser.newContext({ viewport: { width: w, height: HEIGHT } });
      const page = await ctx.newPage();
      await page.goto(at(CARDS), { waitUntil: "networkidle" });
      await page.evaluate(() => document.fonts && document.fonts.ready);
      const o = await page.evaluate(OVERFLOW_FN);
      const count = () => page.locator("[data-deck-count]").innerText();
      const first = await count();
      // 띠에 초점을 두고 오른쪽 화살표 두 번, 왼쪽 한 번.
      await page.locator("[data-deck-view]").focus();
      await page.keyboard.press("ArrowRight");
      await page.keyboard.press("ArrowRight");
      await page.waitForTimeout(150);
      const afterRight = await count();
      const visibleIdx = await page.evaluate(() => {
        const v = document.querySelector("[data-deck-view]");
        const vr = v.getBoundingClientRect();
        return [...document.querySelectorAll(".deck-item")].findIndex((it) => Math.abs(it.getBoundingClientRect().left - vr.left) < 2) + 1;
      });
      await page.keyboard.press("ArrowLeft");
      await page.waitForTimeout(150);
      const afterLeft = await count();
      // 단추: Tab 으로 "다음" 에 가서 Enter.
      const next = page.locator("[data-deck-next]");
      await next.focus();
      await page.keyboard.press("Enter");
      await page.waitForTimeout(150);
      const afterNext = await count();
      const prevBtn = page.locator("[data-deck-prev]");
      await prevBtn.focus();
      await page.keyboard.press("Enter");
      await page.waitForTimeout(150);
      const afterPrev = await count();
      const total = await page.locator(".deck-item").count();
      const live = await page.locator("[data-deck-count]").getAttribute("aria-live");
      const o2 = await page.evaluate(OVERFLOW_FN);
      if (w === 390) {
        await page.screenshot({ path: path.join(shotDir, "cards_390_card3.png"), fullPage: false });
        result.screenshots.push("cards_390_card3.png");
      }
      const ok = o.scrollWidth <= o.innerWidth && o2.scrollWidth <= o2.innerWidth && first === `1 / ${total}` && afterRight === `3 / ${total}` && visibleIdx === 3
        && afterLeft === `2 / ${total}` && afterNext === `3 / ${total}` && afterPrev === `2 / ${total}` && live === "polite";
      rows.push({ width: w, scrollWidth: o.scrollWidth, innerWidth: o.innerWidth, first, afterRight, visibleIdx, afterLeft, afterNext, afterPrev, total, live, ok });
      await ctx.close();
    }
    // 스크립트 끔: 카드가 세로로 이어 놓이고, 띠 단추는 보이지 않고, 가로 스크롤이 없다.
    const nojs = [];
    for (const w of [360, 1280]) {
      const ctx = await browser.newContext({ viewport: { width: w, height: HEIGHT }, javaScriptEnabled: false });
      const page = await ctx.newPage();
      await page.goto(at(CARDS), { waitUntil: "load" });
      const info = await page.evaluate(() => {
        const items = [...document.querySelectorAll(".deck-item")].map((it) => it.getBoundingClientRect());
        const stacked = items.every((r, i) => i === 0 || (r.top >= items[i - 1].bottom - 1 && Math.abs(r.left - items[0].left) < 2));
        const controls = document.querySelector("[data-deck-controls]");
        return {
          items: items.length, stacked, all_visible: items.every((r) => r.width > 0 && r.height > 0),
          controls_hidden: !controls || getComputedStyle(controls).display === "none",
          scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
        };
      });
      await page.screenshot({ path: path.join(shotDir, `cards_${w}_nojs.png`), fullPage: true });
      result.screenshots.push(`cards_${w}_nojs.png`);
      nojs.push({ width: w, ...info, ok: info.items > 0 && info.stacked && info.all_visible && info.controls_hidden && info.scrollWidth <= info.innerWidth });
      await ctx.close();
    }
    result.cards = { rows, nojs, ok: rows.every((r) => r.ok) && nojs.every((r) => r.ok) };
  }
} catch (e) {
  result.error = String(e && e.stack ? e.stack : e);
} finally {
  await browser.close();
  server.close();
  if (tmpBuild) fs.rmSync(tmpBuild, { recursive: true, force: true });
}

// ---- 판정 ----
const contrastCount = (list) => list.reduce((n, x) => n + x.violations.filter((v) => v.id === "color-contrast").reduce((m, v) => m + v.count, 0), 0);
const otherCount = (list) => list.reduce((n, x) => n + x.violations.filter((v) => v.id !== "color-contrast").reduce((m, v) => m + v.count, 0), 0);
const summary = {
  horizontal_scroll: { criterion: "0", value: result.overflow.filter((o) => !o.ok).length, ok: result.overflow.every((o) => o.ok) },
  contrast_light: { criterion: "0", value: contrastCount(result.axe.light) },
  contrast_dark: { criterion: "0", value: contrastCount(result.axe.dark) },
  axe_other_light: { criterion: "0(참고)", value: otherCount(result.axe.light) },
  axe_other_dark: { criterion: "0(참고)", value: otherCount(result.axe.dark) },
  zoom_200: { criterion: "가로 스크롤 0 · 잘림 0", value: result.zoom.map((z) => `${z.page}/${z.mode}: sw ${z.scrollWidth}/${z.innerWidth}, 잘림 ${z.clipped.length}`).join("; "), ok: result.zoom.every((z) => z.ok) },
  keyboard: { criterion: "전부 닿음 · 초점 표시", value: result.keyboard && `${result.keyboard.reached}/${result.keyboard.total}, 초점 표시 없음 ${result.keyboard.no_focus_ring.length}`, ok: !!result.keyboard?.ok },
  slow_3g: { criterion: "≤ 3000ms", value: result.slow.map((s) => `${s.page} ${s.first_text_paint_ms}ms`).join(", "), ok: result.slow.length > 0 && result.slow.every((s) => s.ok) },
  broken_links: { criterion: "0", value: result.links?.broken.length, ok: !!result.links?.ok },
  search: { criterion: "≥ 9/10", value: result.search && `${result.search.pass}/10`, ok: !!result.search?.ok },
  title60: { criterion: "잘림 없음", value: result.title60 && `${result.title60.chars}자, 첫 화면 ${result.title60.home_ok}, 이슈 ${result.title60.issue_ok}`, ok: !!result.title60?.ok },
  reduced_motion: { criterion: "0s", value: result.reduced_motion?.bad.length, ok: !!result.reduced_motion?.ok },
  cards: {
    criterion: "폭 넷 가로 스크롤 0 · 화살표와 단추로 다음/이전 · 스크립트 없이 세로",
    value: result.cards && `${result.cards.rows.filter((r) => r.ok).length}/${result.cards.rows.length} 폭, 스크립트 끔 ${result.cards.nojs.filter((r) => r.ok).length}/${result.cards.nojs.length}`,
    ok: !!result.cards?.ok,
  },
};
summary.contrast_light.ok = summary.contrast_light.value === 0;
summary.contrast_dark.ok = summary.contrast_dark.value === 0;
summary.axe_other_light.ok = summary.axe_other_light.value === 0;
summary.axe_other_dark.ok = summary.axe_other_dark.value === 0;
result.summary = summary;
result.shot_dir = shotDir;
result.shot_count = result.screenshots.length;

fs.writeFileSync(path.join(shotDir, "result.json"), JSON.stringify(result, null, 2));
console.log(JSON.stringify({ shot_dir: shotDir, shots: result.shot_count, error: result.error, summary }, null, 2));
if (result.error) process.exit(2);
const gate = ["horizontal_scroll", "contrast_light", "contrast_dark", "zoom_200", "keyboard", "slow_3g", "broken_links", "search", "cards"];
process.exit(gate.every((k) => summary[k].ok) ? 0 : 1);
