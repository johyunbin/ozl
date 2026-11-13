// 공개용 빌드의 콘텐츠 보안 정책 점검(설계 6-1). 예시 자료를 공개용 모양으로 바꾼 사본으로 임시 폴더에 공개용 빌드를 하고,
// 127.0.0.1 의 빈 포트에 띄워 첫 화면, 이슈 화면, 카드 화면, 검색을 연다. 정책 위반(securitypolicyviolation)이 0건이고
// 검색이 결과를 내고 서비스 워커가 등록되는지 본다. 끝나면 서버를 내리고 임시 폴더를 지운다.
// 쓰는 법(apps/web 에서): npm run check:csp   종료 코드 0 통과, 1 실패, 2 점검 실패.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { serve } from "../scripts/static-server.mjs";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(WEB_ROOT, ".pw-browsers");
const { chromium } = await import("playwright");

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ozl-web-csp-"));
const data = path.join(tmp, "data");
const out = path.join(tmp, "out");
let code = 0;
let srv = null;
let browser = null;
try {
  let r = spawnSync("node", ["scripts/public-sample.mjs", "sample-data", data], { cwd: WEB_ROOT, encoding: "utf-8" });
  if (r.status !== 0) throw new Error(`공개용 예시 사본 실패\n${r.stderr}`);
  r = spawnSync("npm", ["run", "build:public"], {
    cwd: WEB_ROOT, encoding: "utf-8",
    env: { ...process.env, OZL_SITE_DATA: data, OZL_WEB_OUT: out, OZL_REPORT_CONTACT: "test@example.invalid" },
  });
  if (r.status !== 0) throw new Error(`공개용 빌드 실패(${r.status})\n${r.stdout.slice(-2000)}\n${r.stderr.slice(-2000)}`);
  srv = await serve({ root: out, base: "/" });
  browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 800 } });
  const page = await ctx.newPage();
  const violations = [];
  await page.addInitScript(() => {
    window.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI}`));
  });
  page.on("console", (m) => { if (/Content Security Policy/i.test(m.text())) violations.push(`console: ${m.text().slice(0, 200)}`); });
  const rows = [];
  for (const p of ["", "i/hanbit-bus-fare-400/", "i/hanbit-bus-fare-400/cards/", "search/?q=%EB%A6%AC%EC%BD%9C"]) {
    await page.goto(srv.url("") + p, { waitUntil: "networkidle" });
    if (p.startsWith("search/")) {
      await page.waitForFunction(() => {
        const s = document.querySelector("[data-search-status]")?.textContent || "";
        return s && s !== "찾는 중";
      }, null, { timeout: 15000 }).catch(() => {});
    }
    const v = await page.evaluate(() => window.__csp);
    const meta = await page.locator('meta[http-equiv="Content-Security-Policy"]').count();
    const results = p.startsWith("search/") ? await page.locator("[data-search-results] li").count() : null;
    const sw = await page.evaluate(async () => !!(await navigator.serviceWorker.getRegistration()));
    rows.push({ page: p || "(첫 화면)", meta, violations: v, results, sw });
    violations.push(...v.map((x) => `${p}: ${x}`));
  }
  const searchOk = (rows.find((x) => x.results !== null)?.results ?? 0) > 0;
  const ok = violations.length === 0 && rows.every((x) => x.meta === 1) && searchOk;
  for (const x of rows) console.log(`[csp] ${x.page}: meta ${x.meta} · 위반 ${x.violations.length}${x.results !== null ? ` · 검색 결과 ${x.results}` : ""} · 서비스 워커 ${x.sw ? "등록" : "없음"}`);
  for (const v of violations) console.log(`[csp]   ${v}`);
  console.log(`[csp] ${ok ? "통과" : "실패"}`);
  if (!ok) code = 1;
  await ctx.close();
} catch (e) {
  console.error(String(e && e.stack ? e.stack : e));
  code = 2;
} finally {
  if (browser) await browser.close();
  if (srv) await srv.close();
  fs.rmSync(tmp, { recursive: true, force: true });
}
process.exit(code);
