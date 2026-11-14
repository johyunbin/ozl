// 글 화면과 첫 화면 점검(명세 6절): 폰 폭 360 에서 가로 넘침 0, 대비(axe color-contrast) 위반 0,
// 각주 링크가 출처 줄로 가는지, 접힘(details)에 키보드로 닿는지. 폰 390 과 데스크톱 1280 의 전체 화면 사진을 남긴다.
//   node checks/article.mjs --build <미리보기 결과 폴더> --shots <사진 폴더> [slug ...]
// slug 를 주지 않으면 결과 폴더의 i/ 아래 글 화면을 모두 본다. 하나라도 어긋나면 종료 코드 1.
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";
import AxeBuilder from "@axe-core/playwright";
import { serve } from "../scripts/static-server.mjs";

const args = process.argv.slice(2);
const opt = (k) => {
  const i = args.indexOf(k);
  if (i < 0) return undefined;
  const v = args[i + 1];
  args.splice(i, 2);
  return v;
};
const build = path.resolve(opt("--build") || "../../private/out/web_preview");
const shots = opt("--shots");
const base = opt("--base") || "/preview/";
let slugs = args;
if (!slugs.length) {
  slugs = fs.readdirSync(path.join(build, "i")).filter((s) => fs.existsSync(path.join(build, "i", s, "check", "index.html")));
}
if (shots) fs.mkdirSync(shots, { recursive: true });

const srv = await serve({ root: build, base });
const origin = srv.origin;
let browser;
try {
  browser = await chromium.launch();
} catch {
  browser = await chromium.launch({ channel: "chrome" });
}
const problems = [];
const report = [];
const pages = [["home", base], ...slugs.map((s) => [s, `${base}i/${s}/`])];

for (const scheme of ["light", "dark"]) {
  for (const [name, p] of pages) {
    for (const width of [360, 390, 1280]) {
      const ctx = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: scheme, deviceScaleFactor: width < 768 ? 2 : 1 });
      const page = await ctx.newPage();
      await page.goto(origin + p, { waitUntil: "networkidle" });
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (over > 0) problems.push(`${name} ${width} ${scheme}: 가로 넘침 ${over}px`);
      if (width === 360) {
        const axe = await new AxeBuilder({ page }).withRules(["color-contrast"]).analyze();
        for (const v of axe.violations) for (const n of v.nodes) problems.push(`${name} ${scheme}: 대비 ${n.target.join(" ")} ${n.any?.[0]?.message ?? ""}`);
      }
      if (name !== "home" && width === 390 && scheme === "light") {
        // 각주: 모든 위 첨자 링크가 있는 출처 줄을 가리키는지
        const bad = await page.evaluate(() => [...document.querySelectorAll("sup.fn a")].filter((a) => !document.getElementById(a.getAttribute("href").slice(1))).length);
        const nFn = await page.locator("sup.fn a").count();
        if (bad) problems.push(`${name}: 출처 줄이 없는 각주 ${bad}개`);
        // 키보드: Tab 으로 접힘 요약에 닿는지
        const summaries = await page.locator("summary").count();
        const reached = new Set();
        for (let i = 0; i < 300; i++) {
          await page.keyboard.press("Tab");
          const t = await page.evaluate(() => (document.activeElement?.tagName === "SUMMARY" ? document.activeElement.textContent.trim() : ""));
          if (t) reached.add(t);
          if (reached.size >= summaries) break;
        }
        if (reached.size < summaries) problems.push(`${name}: 키보드로 닿지 않는 접힘 ${summaries - reached.size}개`);
        report.push(`${name}: 각주 링크 ${nFn}개, 접힘 ${summaries}개 키보드 도달 ${reached.size}개`);
      }
      if (name === "home" && width === 390 && scheme === "light") {
        // 분야 칩: 둘째 칩을 누르면 그 분야 줄만 남는지
        const chips = await page.locator(".chips label").count();
        if (chips > 1) {
          const all = await page.locator(".rank > li:visible").count();
          await page.locator(".chips label").nth(1).click();
          const some = await page.locator(".rank > li:visible").count();
          const other = await page.locator('.rank > li:visible:not([data-field="f0"])').count();
          if (!(some > 0 && other === 0 && (chips === 2 || some < all))) problems.push(`home: 분야 칩 거르기가 맞지 않다(전체 ${all}, 거른 뒤 ${some}, 다른 분야 ${other})`);
          report.push(`home: 분야 칩 ${chips - 1}개, 첫 분야 ${some}/${all}줄`);
          await page.locator(".chips label").first().click();
        }
      }
      if (shots && width !== 360 && (scheme === "light" || width === 390)) {
        if (width !== 1280) await page.evaluate(() => document.querySelectorAll("details").forEach((d) => (d.open = true)));
        // 붙어 있는 머리 줄이 전체 화면 사진 가운데에 찍히지 않게 사진에서만 풀어 둔다.
        await page.addStyleTag({ content: ".site-header{position:static!important}" });
        await page.screenshot({ path: path.join(shots, `${name}_${width}_${scheme}.png`), fullPage: true });
      }
      await ctx.close();
    }
  }
}
await browser.close();
await srv.close();
for (const r of report) console.log(`[article] ${r}`);
for (const p of problems) console.log(`[article] 어긋남: ${p}`);
console.log(`[article] 화면 ${pages.length}개 · 어긋난 것 ${problems.length}개${shots ? ` · 사진 ${shots}` : ""}`);
process.exit(problems.length ? 1 : 0);
