// 카드 그림 찍기(설계 1-14, 4-17). 미리보기 빌드의 그림 전용 화면(i/<slug>/cards/print/)을 열어
// 장마다 1080×1350 PNG 로 찍고, 찍은 뒤 스스로 확인해 cards.json 을 함께 쓴다. 게시는 하지 않는다.
//
// 쓰는 법(apps/web 에서, 미리보기 빌드가 먼저 끝나 있어야 한다):
//   npm run cards                                   # 결과 폴더 기본값의 모든 이슈
//   npm run cards -- --build <결과 폴더> --out <그림 폴더> [slug ...]
// 환경 값: OZL_WEB_OUT(빌드 결과 폴더), OZL_CARDS_OUT(그림 폴더), OZL_SITE_DATA(대조할 자료 폴더)
// 그림 자리: <그림 폴더>/<slug>/r<판>/NN.png + cards.json (기본 <저장소>/private/out/cards)
//
// 스스로 확인하는 것(하나라도 어긋나면 종료 코드 1):
//   1. 파일 크기가 0 이 아니고, PNG 머리에 적힌 크기가 1080×1350 이다.
//   2. 카드 안에서 넘친 상자가 없다(본문 상자 scrollHeight > clientHeight, 또는 카드 밖으로 나간 글자 상자 0개).
//   3. 그림의 장 수가 카드 보기 화면(i/<slug>/cards/)의 장 수와 같다.
//   4. 장마다 실린 글이 그 장의 화면 글에 들어 있다.
//   5. 자료에서 온 문장(from: data), 판정, 출처, 판 번호가 그 판의 사본(issues/<slug>/r/<판>.json)과 같다.
//      판 사본이 없으면(미리보기 작업본) 최신 본문과 대조하고 copy: "latest" 로 적는다.
//      장을 넘겨 이은 글(chain 이 같은 조각)은 장 차례로 이은 글 전체가 사본의 문장과 글자 하나 다르지 않아야 한다.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { serve } from "./static-server.mjs";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "../..");
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(WEB_ROOT, ".pw-browsers");
const { chromium } = await import("playwright");

const args = process.argv.slice(2);
const opt = (name) => {
  const i = args.indexOf(name);
  if (i < 0) return undefined;
  const v = args[i + 1];
  args.splice(i, 2);
  return v;
};
const build = path.resolve(opt("--build") || process.env.OZL_WEB_OUT || path.join(REPO_ROOT, "private/out/web_preview"));
const outRoot = path.resolve(opt("--out") || process.env.OZL_CARDS_OUT || path.join(REPO_ROOT, "private/out/cards"));
const dataDir = path.resolve(opt("--data") || process.env.OZL_SITE_DATA || path.join(WEB_ROOT, "sample-data"));
const BASE = opt("--base") || "/preview/";
let slugs = args.filter((a) => !a.startsWith("--"));

if (!fs.existsSync(path.join(build, "i"))) {
  console.error(`[cards] 빌드 결과가 없다: ${build} (npm run build:preview 를 먼저 돌린다)`);
  process.exit(2);
}
if (!slugs.length) {
  slugs = fs.readdirSync(path.join(build, "i")).filter((s) => fs.existsSync(path.join(build, "i", s, "cards/print/index.html"))).sort();
}
if (!slugs.length) {
  console.error("[cards] 그림 전용 화면이 없다. 공개용 빌드에는 만들지 않는다 — 미리보기 빌드를 준다.");
  process.exit(2);
}

// ---- 판 사본 읽기 ----
function copyFor(slug, rev) {
  const r = path.join(dataDir, "issues", slug, "r", `${rev}.json`);
  if (rev !== null && fs.existsSync(r)) return { body: JSON.parse(fs.readFileSync(r, "utf-8")), copy: `issues/${slug}/r/${rev}.json` };
  const l = path.join(dataDir, "issues", `${slug}.json`);
  if (fs.existsSync(l)) return { body: JSON.parse(fs.readFileSync(l, "utf-8")), copy: "latest" };
  return { body: null, copy: null };
}
function strings(o, out = new Set()) {
  if (typeof o === "string") out.add(o);
  else if (Array.isArray(o)) o.forEach((x) => strings(x, out));
  else if (o && typeof o === "object") Object.values(o).forEach((x) => strings(x, out));
  return out;
}
function claimsOf(body) {
  return (body?.verdicts?.groups || []).flatMap((g) => g.claims || []);
}
function sourcesOf(o, out = []) {
  if (Array.isArray(o)) o.forEach((x) => sourcesOf(x, out));
  else if (o && typeof o === "object") {
    if (Array.isArray(o.sources)) out.push(...o.sources);
    Object.values(o).forEach((x) => sourcesOf(x, out));
  }
  return out;
}

function pngSize(file) {
  const b = fs.readFileSync(file);
  if (b.length < 24 || b.toString("ascii", 1, 4) !== "PNG") return null;
  return { width: b.readUInt32BE(16), height: b.readUInt32BE(20), bytes: b.length };
}

const norm = (s) => String(s).replace(/\s+/g, " ").trim();
const srv = await serve({ root: build, base: BASE });
const browser = await chromium.launch();
const report = [];
let failed = 0;
try {
  const ctx = await browser.newContext({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: 1, colorScheme: "light" });
  const page = await ctx.newPage();
  for (const slug of slugs) {
    const problems = [];
    const resp = await page.goto(srv.url(`i/${slug}/cards/print/`), { waitUntil: "networkidle" });
    if (!resp || resp.status() !== 200) {
      problems.push(`그림 전용 화면을 열지 못했다(${resp?.status()})`);
      report.push({ slug, ok: false, problems });
      failed++;
      continue;
    }
    await page.evaluate(() => document.fonts.ready);
    const data = JSON.parse(await page.locator("#ozl-cards").textContent());
    const dir = path.join(outRoot, slug, `r${data.rev ?? "x"}`);
    fs.mkdirSync(dir, { recursive: true });
    for (const f of fs.readdirSync(dir)) if (/^\d+\.png$/.test(f) || f === "cards.json") fs.rmSync(path.join(dir, f));

    // 넘침 재기
    const measures = await page.evaluate(() => [...document.querySelectorAll("[data-print-card]")].map((slot) => {
      const card = slot.querySelector(".card-in");
      const body = slot.querySelector("[data-card-body]");
      const cr = card.getBoundingClientRect();
      const br = body.getBoundingClientRect();
      const over = [];
      if (body.scrollHeight > body.clientHeight + 1) over.push({ el: "본문 상자", why: `세로 ${body.scrollHeight} > ${body.clientHeight}` });
      if (body.scrollWidth > body.clientWidth + 1) over.push({ el: "본문 상자", why: `가로 ${body.scrollWidth} > ${body.clientWidth}` });
      for (const el of slot.querySelectorAll(".card-in *")) {
        const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
        if (!hasText) continue;
        const cs = getComputedStyle(el);
        if (cs.position === "absolute" && cs.clipPath.startsWith("inset(50%")) continue; // 화면 읽기 전용
        const r = el.getBoundingClientRect();
        const inBody = body.contains(el);
        const lim = inBody ? br : cr;
        if (r.bottom > lim.bottom + 1 || r.right > lim.right + 1) over.push({ el: el.className || el.tagName.toLowerCase(), text: el.textContent.trim().slice(0, 30), why: "상자 밖" });
        if (el.scrollHeight > el.clientHeight + 1 && cs.overflowY !== "visible") over.push({ el: el.className, why: "세로 잘림" });
      }
      // 실제로 쓴 높이: 본문 안 마지막 글 상자의 아래 끝까지.
      let bottom = br.top;
      for (const el of body.querySelectorAll("*")) bottom = Math.max(bottom, el.getBoundingClientRect().bottom);
      return {
        n: Number(slot.dataset.printCard), width: Math.round(cr.width), height: Math.round(cr.height),
        used: Math.round(bottom - br.top), room: Math.round(body.clientHeight), over,
        text: slot.innerText.replace(/\s+/g, " ").trim(),
      };
    }));

    // 카드 보기 화면의 장 수
    const page2 = await ctx.newPage();
    await page2.goto(srv.url(`i/${slug}/cards/`), { waitUntil: "networkidle" });
    const screenCount = await page2.locator(".deck-item").count();
    await page2.close();
    if (screenCount !== data.total || measures.length !== data.total) problems.push(`장 수가 다르다: 그림 ${measures.length}, 자료 ${data.total}, 화면 ${screenCount}`);

    // 판 사본과 대조
    const { body: copy, copy: copyName } = copyFor(slug, data.rev);
    const all = copy ? strings(copy) : new Set();
    const claims = claimsOf(copy);
    const parts = claims.flatMap((c) => c.parts || []);
    const srcs = copy ? sourcesOf(copy) : [];
    if (!copy) problems.push("대조할 판 사본도 최신 본문도 없다");
    if (copy && copy.rev !== data.rev) problems.push(`판 번호가 다르다: 카드 ${data.rev}, 사본 ${copy.rev}`);
    if (copy && data.summary) {
      const s = copy.verdicts?.summary || {};
      for (const [k, v] of Object.entries(data.summary)) if ((s[k] ?? 0) !== v) problems.push(`판정 집계가 다르다: ${k} 카드 ${v}, 사본 ${s[k] ?? 0}`);
    }

    const cardsOut = [];
    const chains = new Map(); // chain → { text, first }
    for (const c of data.cards) {
      const m = measures.find((x) => x.n === c.n);
      const file = `${String(c.n).padStart(2, "0")}.png`;
      const fp = path.join(dir, file);
      await page.locator(`[data-print-card="${c.n}"]`).screenshot({ path: fp });
      const size = pngSize(fp);
      const cp = [];
      if (!size || size.bytes === 0) cp.push("그림 파일이 비었다");
      else if (size.width !== 1080 || size.height !== 1350) cp.push(`그림 크기 ${size.width}×${size.height}`);
      if (m.over.length) cp.push(`넘친 상자 ${m.over.length}개: ${m.over.slice(0, 3).map((o) => `${o.el} ${o.why}${o.text ? ` "${o.text}"` : ""}`).join("; ")}`);
      for (const t of c.texts) {
        if (!m.text.includes(norm(t.text))) cp.push(`화면 글에 없음: "${t.text.slice(0, 30)}"`);
        if (t.chain) {
          if (t.from !== "data") cp.push(`이은 글이 자료 글이 아니다: "${t.text.slice(0, 30)}"`);
          const ch = chains.get(t.chain) || { text: "", first: c.n };
          ch.text += t.text;
          chains.set(t.chain, ch);
        } else if (copy && t.from === "data" && !all.has(t.text)) cp.push(`사본에 없는 문장: "${t.text.slice(0, 30)}"`);
      }
      for (const v of c.verdicts) {
        const hit = claims.find((x) => x.gist === v.text) || parts.find((x) => x.gist === v.text);
        if (copy && !hit) cp.push(`사본에 없는 주장: "${v.text.slice(0, 30)}"`);
        else if (hit && hit.verdict !== v.verdict) cp.push(`판정이 다르다: "${v.text.slice(0, 20)}" 카드 ${v.verdict}, 사본 ${hit.verdict}`);
      }
      for (const s of c.sources) {
        const hostOf = (u) => { try { return new URL(u).host; } catch { return ""; } };
        const hit = srcs.some((x) => ((x.by || "") === s.by || (!x.by && x.title === s.by)) && (s.title ? (x.title || "") === s.title : true) && (s.host ? hostOf(x.url || "") === s.host : true));
        if (copy && !hit) cp.push(`사본에 없는 출처: ${s.by} · ${s.title} ${s.host}`);
      }
      if (cp.length) problems.push(...cp.map((p) => `${c.n}장: ${p}`));
      cardsOut.push({
        file, n: c.n, kind: c.kind, label: c.label, continued: c.cont,
        size: size ? `${size.width}x${size.height}` : null, bytes: size?.bytes ?? 0,
        room_px: m.room, used_px: m.used, estimate_px: Math.round((c.est_em ?? 0) * 48),
        texts: c.texts, verdicts: c.verdicts, sources: c.sources,
      });
    }

    for (const [, ch] of chains) {
      if (copy && !all.has(ch.text)) problems.push(`${ch.first}장부터 이은 글이 사본의 문장과 다르다: "${ch.text.slice(0, 30)}"`);
    }

    const out = {
      made_at: new Date().toISOString(), slug, title: data.title, rev: data.rev, date: data.date, example: data.example,
      copy: copyName, fixed_path: data.fixed ? data.fixed_path : null, issue_path: data.issue_path,
      total: data.total, screen_total: screenCount, summary: data.summary, cards: cardsOut,
      check: { ok: problems.length === 0, problems },
    };
    fs.writeFileSync(path.join(dir, "cards.json"), JSON.stringify(out, null, 1));
    if (problems.length) failed++;
    report.push({ slug, rev: data.rev, dir, cards: data.total, copy: copyName, ok: problems.length === 0, problems });
  }
  await ctx.close();
} finally {
  await browser.close();
  await srv.close();
}

for (const r of report) {
  console.log(`[cards] ${r.ok ? "통과" : "실패"} ${r.slug} · ${r.rev ?? "?"}판 · ${r.cards ?? 0}장 · 대조 ${r.copy ?? "없음"} → ${r.dir ?? ""}`);
  for (const p of r.problems) console.log(`[cards]   ${p}`);
}
console.log(`[cards] 이슈 ${report.length}건 · 실패 ${failed}건`);
process.exit(failed ? 1 : 0);
