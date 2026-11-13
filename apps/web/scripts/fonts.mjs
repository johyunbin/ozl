// Pretendard 를 사이트 안에 싣는다(설계 3-4). 400·600·700 굵기의 woff2 동적 부분집합만 복사한다.
import fs from "node:fs";
import path from "node:path";
import { OUT_MARK, outDir, WEB_ROOT } from "./paths.mjs";

const out = outDir();
// astro build 가 결과 폴더를 비우면 guard.mjs 가 남긴 표식도 지워진다. 다시 남긴다.
fs.writeFileSync(path.join(out, OUT_MARK), "ozl web build output\n");
const src = path.join(WEB_ROOT, "node_modules/pretendard/dist/web/static");
const css = fs.readFileSync(path.join(src, "pretendard-dynamic-subset.css"), "utf-8");
const keep = new Set(["400", "600", "700"]);
const blocks = css.match(/@font-face\s*{[^}]*}/g) ?? [];
const dest = path.join(out, "fonts");
fs.mkdirSync(path.join(dest, "woff2"), { recursive: true });
const parts = [];
let files = 0;
for (const b of blocks) {
  const w = b.match(/font-weight:\s*(\d+)/)?.[1];
  if (!keep.has(w)) continue;
  const file = b.match(/url\(\.\/woff2-dynamic-subset\/([^)]+\.woff2)\)/)?.[1];
  const range = b.match(/unicode-range:\s*([^;]+);/)?.[1];
  if (!file || !range) continue;
  fs.copyFileSync(path.join(src, "woff2-dynamic-subset", file), path.join(dest, "woff2", file));
  files++;
  parts.push(`@font-face{font-family:'Pretendard';font-style:normal;font-display:swap;font-weight:${w};src:url(./woff2/${file}) format('woff2');unicode-range:${range.trim()}}`);
}
const license = css.match(/^\/\*[\s\S]*?\*\//)?.[0] ?? "";
fs.writeFileSync(path.join(dest, "pretendard.css"), `${license}\n${parts.join("\n")}\n`);
console.log(`[fonts] Pretendard 400·600·700 부분집합 ${files}개 → ${dest}`);
