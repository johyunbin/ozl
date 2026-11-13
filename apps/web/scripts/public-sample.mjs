// 예시 자료를 공개용 모양으로 바꾼 사본을 만든다(설계 7-2 끝, 8-3 시험용).
// 사용: node scripts/public-sample.mjs <원본 폴더> <새 폴더>
// internal, publish_state, trend_now, 공개 제외 표시가 붙은 정리 전 항목을 지우고 meta.mode 를 public 으로 바꾼다.
import fs from "node:fs";
import path from "node:path";

const [src, dst] = process.argv.slice(2);
if (!src || !dst) {
  console.error("사용: node scripts/public-sample.mjs <원본 폴더> <새 폴더>");
  process.exit(2);
}
const EXCLUDE = ["개인", "사생활", "범죄 의혹", "선거 판세"];
fs.rmSync(dst, { recursive: true, force: true });
fs.cpSync(src, dst, { recursive: true });
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((f) => (f.isDirectory() ? walk(path.join(d, f.name)) : f.name.endsWith(".json") ? [path.join(d, f.name)] : []));
for (const f of walk(dst)) {
  const rel = path.relative(dst, f);
  const j = JSON.parse(fs.readFileSync(f, "utf-8"));
  if (rel === "meta.json") j.mode = "public";
  if (rel === "index.json") for (const r of j.issues ?? []) delete r.publish_state;
  if (rel.startsWith("issues")) {
    delete j.internal;
    delete j.trend_now;
  }
  if (rel.startsWith("days") && j.topics) j.topics.pre = (j.topics.pre ?? []).filter((p) => !(p.flags ?? []).some((x) => EXCLUDE.includes(x)));
  fs.writeFileSync(f, JSON.stringify(j, null, 1) + "\n");
}
console.log(`[public-sample] ${dst}`);
