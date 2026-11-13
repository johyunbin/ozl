// 깨진 안쪽 링크 검사(설계 8-3 5). 사용: node scripts/check-links.mjs <결과 폴더> <기준 경로>
import fs from "node:fs";
import path from "node:path";

const [root, base = "/"] = process.argv.slice(2);
if (!root) {
  console.error("사용: node scripts/check-links.mjs <결과 폴더> <기준 경로>");
  process.exit(2);
}
const html = [];
const walk = (d) => {
  for (const f of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, f.name);
    if (f.isDirectory()) walk(p);
    else if (f.name.endsWith(".html")) html.push(p);
  }
};
walk(root);
const ids = new Map();
const idsOf = (file) => {
  if (!ids.has(file)) {
    const t = fs.readFileSync(file, "utf-8");
    ids.set(file, new Set([...t.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])));
  }
  return ids.get(file);
};
const resolve = (u) => {
  let rel = decodeURI(u.slice(base.length));
  let p = path.join(root, rel);
  if (rel === "" || rel.endsWith("/")) p = path.join(p, "index.html");
  return fs.existsSync(p) ? p : null;
};
let bad = 0;
let n = 0;
for (const f of html) {
  const t = fs.readFileSync(f, "utf-8");
  const pageUrl = base + path.relative(root, f).split(path.sep).join("/").replace(/index\.html$/, "");
  for (const m of t.matchAll(/\s(?:href|src)="([^"]+)"/g)) {
    let u = m[1].replace(/&amp;/g, "&");
    if (/^(https?:|mailto:|data:|javascript:)/.test(u)) continue;
    if (u.startsWith("#")) u = pageUrl + u;
    if (!u.startsWith(base)) {
      if (u.startsWith("/")) {
        console.log(`기준 경로 밖: ${path.relative(root, f)} → ${u}`);
        bad++;
      }
      continue;
    }
    n++;
    const [p0, frag] = u.split("#");
    const target = resolve(p0.split("?")[0]);
    if (!target) {
      console.log(`없는 쪽: ${path.relative(root, f)} → ${u}`);
      bad++;
      continue;
    }
    if (frag && target.endsWith(".html") && !idsOf(target).has(decodeURIComponent(frag))) {
      console.log(`없는 조각: ${path.relative(root, f)} → ${u}`);
      bad++;
    }
  }
}
console.log(`[links] HTML ${html.length}개 · 안쪽 링크 ${n}개 · 깨진 것 ${bad}개`);
process.exit(bad ? 1 : 0);
