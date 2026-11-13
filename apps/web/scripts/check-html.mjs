// 빌드 결과의 HTML 검사(설계 6-1). 하나라도 있으면 종료 코드 1 로 빌드를 멈춘다.
//   - 실행되는 인라인 <script>(src 가 없고 type 이 자료 블록이 아닌 것) 0개
//   - 인라인 이벤트 속성(onload= 같은 on…=) 0개
//   - javascript: 주소 0개(href, src, action, formaction 등 속성 값)
//   - 공개용이면 쪽마다 콘텐츠 보안 정책 meta 1개
// 사용: node scripts/check-html.mjs [결과 폴더]   (없으면 OZL_BUILD_MODE 에 맞는 기본 결과 폴더)
import fs from "node:fs";
import path from "node:path";
import { buildMode, outDir } from "./paths.mjs";

const root = path.resolve(process.argv[2] || outDir());
const mode = buildMode();
const DATA_TYPES = new Set(["application/json", "application/ld+json", "importmap-off"]);
const files = [];
const walk = (d) => {
  for (const f of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, f.name);
    if (f.isDirectory()) walk(p);
    else if (f.name.endsWith(".html")) files.push(p);
  }
};
walk(root);

const bad = [];
let scripts = 0;
for (const f of files) {
  const rel = path.relative(root, f);
  const t = fs.readFileSync(f, "utf-8");
  for (const m of t.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    scripts++;
    const attrs = m[1];
    const type = (attrs.match(/\btype\s*=\s*["']?([^"'\s>]+)/i)?.[1] || "").toLowerCase();
    const hasSrc = /\bsrc\s*=/i.test(attrs);
    if (!hasSrc && !DATA_TYPES.has(type)) bad.push(`${rel}: 인라인 스크립트(${type || "classic"}) ${m[2].trim().slice(0, 60)}`);
    if (hasSrc && m[2].trim()) bad.push(`${rel}: src 가 있는 스크립트에 본문이 있다`);
  }
  // 태그 안의 속성만 본다(본문 글자는 빼고).
  for (const m of t.matchAll(/<[a-zA-Z][^<>]*>/g)) {
    const tag = m[0];
    const ev = tag.match(/\s(on[a-z]+)\s*=/i);
    if (ev) bad.push(`${rel}: 인라인 이벤트 속성 ${ev[1]} — ${tag.slice(0, 80)}`);
    for (const a of tag.matchAll(/\s([a-z-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))/gi)) {
      const v = (a[3] ?? a[4] ?? a[5] ?? "").replace(/&#x?[0-9a-f]+;?/gi, "").replace(/\s+/g, "").toLowerCase();
      if (v.startsWith("javascript:")) bad.push(`${rel}: javascript: 주소 (${a[1]})`);
    }
  }
  if (mode === "public") {
    const n = (t.match(/<meta http-equiv="Content-Security-Policy"/g) || []).length;
    if (n !== 1) bad.push(`${rel}: 콘텐츠 보안 정책 meta 가 ${n}개`);
  }
}
for (const b of bad.slice(0, 40)) console.log(`[check-html] ${b}`);
console.log(`[check-html] ${mode === "public" ? "공개용" : "미리보기용"} HTML ${files.length}개 · 스크립트 태그 ${scripts}개 · 어긴 것 ${bad.length}개`);
process.exit(bad.length ? 1 : 0);
