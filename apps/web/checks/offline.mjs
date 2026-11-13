// 홈 화면 추가의 저장분 점검(설계 4-18, 8-6). 서비스 워커가 내린 글을 기기에서 지우는지 본다.
//
//   (가) 연결된 채로 이슈 화면을 연다(저장된다).
//   (나) 연결을 끊고 다시 연다 → 저장분과 "연결이 없어 저장된 판을 보여 준다" 띠가 보인다.
//   (다) 그 이슈를 내린 빌드로 바꾸고(같은 빌드 식별자) 다시 연결한다 → 서비스 워커가 offline.json 을 받아 지운다.
//   (라) 다시 연결을 끊고 연다 → 내린 이슈는 더는 보이지 않고, 내리지 않은 이슈의 저장분은 남는다.
//
// 내림은 예시 자료의 사본을 임시 폴더에 떠서 흉내 낸다(sample-data/ 원본은 건드리지 않는다).
// 서버는 127.0.0.1 의 빈 포트에 띄우고 끝나면 내린다.
// 쓰는 법(apps/web 에서): npm run check:offline
// 결과: <저장소>/private/out/screens/offline_<YYYYMMDD_HHMMSS>/result.json + PNG. 종료 코드 0 통과, 1 실패, 2 점검 실패.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { serve } from "../scripts/static-server.mjs";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "../..");
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(WEB_ROOT, ".pw-browsers");
const { chromium } = await import("playwright");

const DOWN = "nuri-battery-recall"; // 내릴 이슈
const KEEP = "hanbit-bus-fare-400"; // 그대로 둘 이슈
const BUILD_ID = "offline-check";

const stamp = () => new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 19).replace(/[-:]/g, "").replace("T", "_");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ozl-web-offline-"));
const shotDir = path.join(REPO_ROOT, "private/out/screens", `offline_${stamp()}`);
fs.mkdirSync(shotDir, { recursive: true });

// ---- 자료 두 벌: 그대로(A), 한 이슈를 내린 것(B) ----
const dataA = path.join(tmp, "data-a");
const dataB = path.join(tmp, "data-b");
fs.cpSync(path.join(WEB_ROOT, "sample-data"), dataA, { recursive: true });
fs.cpSync(path.join(WEB_ROOT, "sample-data"), dataB, { recursive: true });
{
  const rj = (f) => JSON.parse(fs.readFileSync(path.join(dataB, f), "utf-8"));
  const wj = (f, v) => fs.writeFileSync(path.join(dataB, f), JSON.stringify(v, null, 1));
  const body = rj(`issues/${DOWN}.json`);
  const idx = rj("index.json");
  idx.issues = idx.issues.filter((r) => r.slug !== DOWN);
  wj("index.json", idx);
  fs.rmSync(path.join(dataB, "issues", `${DOWN}.json`));
  fs.rmSync(path.join(dataB, "issues", DOWN), { recursive: true, force: true });
  const td = rj("takedowns.json");
  td.push({ id: body.id, rev: body.rev, at: "2099-01-03T12:00:00+09:00" });
  wj("takedowns.json", td);
  // 내보내기는 내린 이슈를 날짜 쪽과 키워드에서도 뺀다. 그 모양을 따른다.
  for (const f of fs.readdirSync(path.join(dataB, "days"))) {
    const d = rj(`days/${f}`);
    if (Array.isArray(d.records)) d.records = d.records.filter((r) => r.slug !== DOWN);
    for (const k of ["new", "ongoing"]) if (d.topics && Array.isArray(d.topics[k])) d.topics[k] = d.topics[k].filter((t) => t.issue_id !== body.id);
    wj(`days/${f}`, d);
  }
  const kw = rj("keywords.json");
  for (const v of Object.values(kw)) if (Array.isArray(v.issues)) v.issues = v.issues.filter((s) => s !== body.id && s !== DOWN);
  wj("keywords.json", kw);
}

function build(data, out) {
  const r = spawnSync("npm", ["run", "build:preview"], {
    cwd: WEB_ROOT, encoding: "utf-8",
    env: { ...process.env, OZL_SITE_DATA: data, OZL_WEB_OUT: out, OZL_BUILD_ID: BUILD_ID },
  });
  if (r.status !== 0) {
    console.error(r.stdout.slice(-3000), r.stderr.slice(-3000));
    throw new Error(`미리보기 빌드 실패(${r.status})`);
  }
}
const outA = path.join(tmp, "out-a");
const outB = path.join(tmp, "out-b");
const result = { made_at: new Date().toISOString(), build_id: BUILD_ID, down: DOWN, keep: KEEP, steps: [], cache_after: null };
let current = outA;
let srv = null;
let browser = null;
let code = 0;
try {
  build(dataA, outA);
  build(dataB, outB);
  srv = await serve({ root: () => current, base: "/preview/" });
  result.origin = srv.origin;
  browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 800 } });
  const page = await ctx.newPage();
  const step = (name, ok, detail) => {
    result.steps.push({ name, ok, ...detail });
    console.log(`[offline] ${ok ? "통과" : "실패"} ${name}${detail?.note ? ` — ${detail.note}` : ""}`);
    if (!ok) code = 1;
  };
  const sw = (type) => page.evaluate((t) => new Promise((ok) => {
    const ch = new MessageChannel();
    ch.port1.onmessage = (e) => ok(e.data);
    navigator.serviceWorker.controller.postMessage({ type: t }, [ch.port2]);
    setTimeout(() => ok({ timeout: true }), 10000);
  }), type);
  const cachedPaths = () => page.evaluate(async () => {
    const out = [];
    for (const k of await caches.keys()) for (const r of await (await caches.open(k)).keys()) out.push(`${k} ${new URL(r.url).pathname}`);
    return out;
  });
  const title = (slug) => JSON.parse(fs.readFileSync(path.join(dataA, "issues", `${slug}.json`), "utf-8")).title;
  const h1 = async () => (await page.locator("h1").first().innerText()).replace(/\s+/g, " ").replace(/^예시\s*/, "").trim();
  const band = async () => (await page.locator("[data-offline-band]").count()) ? await page.locator("[data-offline-band]").innerText() : "";
  const offline = async (v) => { srv.setOffline(v); await ctx.setOffline(v); };

  // (가) 연결된 채로 연다. 처음 연 쪽은 아직 서비스 워커가 맡지 않으므로, 준비된 뒤 다시 연다.
  await page.goto(srv.url(`i/${DOWN}/`), { waitUntil: "networkidle" });
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.waitForFunction(() => !!navigator.serviceWorker.controller, null, { timeout: 10000 }).catch(() => page.reload());
  for (const p of [`i/${DOWN}/`, `i/${DOWN}/cards/`, `i/${KEEP}/`, `i/${KEEP}/r/2/`]) await page.goto(srv.url(p), { waitUntil: "networkidle" });
  const savedA = await sw("saved");
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.getRegistration())?.scope);
  step("(가) 연결된 채로 이슈 화면을 연다", (savedA.saved || []).some((x) => x.slug === DOWN) && scope?.endsWith("/preview/"), {
    note: `scope ${scope} · 저장 ${(savedA.saved || []).map((x) => `${x.slug}(${x.pages.length}쪽)`).join(", ")}`, scope, saved: savedA.saved,
  });

  // (나) 연결을 끊고 다시 연다.
  await offline(true);
  await page.goto(srv.url(`i/${DOWN}/`), { waitUntil: "domcontentloaded" });
  const bH1 = await h1();
  const bBand = await band();
  await page.screenshot({ path: path.join(shotDir, "b_offline_saved.png"), fullPage: false });
  step("(나) 연결을 끊고 다시 연다", bH1 === title(DOWN) && bBand.startsWith("연결이 없어 저장된 판을 보여 준다(저장 시각 "), { note: `제목 "${bH1}" · 띠 "${bBand}"`, h1: bH1, band: bBand });

  // (다) 내린 빌드로 바꾸고 다시 연결한다. 첫 화면을 연 뒤 서비스 워커에 목록 대조를 시킨다(연결되면 쪽이 하는 일과 같다).
  current = outB;
  await offline(false);
  await page.goto(srv.url(""), { waitUntil: "networkidle" });
  // 쪽의 등록 스크립트도 연결되면 대조를 시킨다. 어느 쪽이 지웠든, 대조가 끝난 뒤 저장분과 저장 목록을 본다.
  const s = await sw("sync");
  const savedC = await sw("saved");
  const leftC = (await cachedPaths()).filter((p) => p.includes(DOWN));
  step("(다) 내린 빌드로 바꾸고 다시 연결한다", s.ok === true && leftC.length === 0 && !(savedC.saved || []).some((x) => x.slug === DOWN), {
    note: `대조 ${s.ok ? "됨" : "안 됨"} · 남은 내린 이슈 저장분 ${leftC.length}건 · 저장 목록 ${(savedC.saved || []).map((x) => x.slug).join(", ")}`, sync: s, saved: savedC.saved,
  });

  // (라) 다시 연결을 끊고 연다.
  await offline(true);
  await page.goto(srv.url(`i/${DOWN}/`), { waitUntil: "domcontentloaded" });
  const dH1 = await h1();
  const dBand = await band();
  const bodyText = await page.locator("body").innerText();
  await page.screenshot({ path: path.join(shotDir, "d_offline_after_takedown.png"), fullPage: true });
  await page.goto(srv.url(`i/${DOWN}/cards/`), { waitUntil: "domcontentloaded" });
  const dCardsH1 = await h1();
  await page.goto(srv.url(`i/${KEEP}/`), { waitUntil: "domcontentloaded" });
  const keepH1 = await h1();
  const keepBand = await band();
  await page.goto(srv.url(`i/${KEEP}/r/2/`), { waitUntil: "domcontentloaded" });
  const keepRevH1 = await h1();
  const after = await cachedPaths();
  result.cache_after = after;
  const gone = !bodyText.includes(title(DOWN)) && dH1 !== title(DOWN) && dCardsH1 !== title(DOWN) && !after.some((p) => p.includes(DOWN));
  step("(라) 다시 연결을 끊고 연다", gone, {
    note: `내린 이슈 쪽 제목 "${dH1}", 카드 쪽 제목 "${dCardsH1}", 띠 "${dBand}" · 캐시에 남은 내린 이슈 ${after.filter((p) => p.includes(DOWN)).length}건`,
    h1: dH1, cards_h1: dCardsH1, band: dBand,
  });
  step("(라-2) 내리지 않은 이슈의 저장분은 남는다", keepH1 === title(KEEP) && keepBand.startsWith("연결이 없어") && keepRevH1 === title(KEEP), {
    note: `최신판 "${keepH1}" · 2판 "${keepRevH1}"`,
  });
  await offline(false);
  await ctx.close();
} catch (e) {
  result.error = String(e && e.stack ? e.stack : e);
  console.error(result.error);
  code = 2;
} finally {
  if (browser) await browser.close();
  if (srv) await srv.close();
  fs.rmSync(tmp, { recursive: true, force: true });
}
result.ok = code === 0;
fs.writeFileSync(path.join(shotDir, "result.json"), JSON.stringify(result, null, 2));
console.log(`[offline] ${code === 0 ? "통과" : "실패"} · 결과 ${shotDir}`);
process.exit(code);
