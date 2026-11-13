// 예시 자료의 모양이 내보내기와 같은지 본다(설계 8-4). 실패로 끝내지 않고 목록만 낸다.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { REPO_ROOT, WEB_ROOT } from "./paths.mjs";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ozl-shape-"));
const desk = path.join(tmp, "desk");
fs.cpSync(path.join(REPO_ROOT, "tests/fixtures/issues"), path.join(desk, "issues"), { recursive: true });
const exp = path.join(desk, "out");
const r = spawnSync(path.join(REPO_ROOT, ".venv/bin/python"), ["-m", "ozl.issues", "export", "--preview", "--out", exp], {
  cwd: REPO_ROOT, env: { ...process.env, OZL_DESK_ROOT: desk }, encoding: "utf-8",
});
if (r.status !== 0) {
  console.log(`[shape] 내보내기 실패(코드 ${r.status}): ${r.stderr || r.stdout}`);
  process.exit(0);
}
const keys = (v, pre = "", acc = new Set()) => {
  if (Array.isArray(v)) v.forEach((x) => keys(x, `${pre}[]`, acc));
  else if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) {
    // 사전 열쇠가 자료 값인 곳(keywords.json 의 키워드, numbers 의 칸 이름, 판정 요약)은 하나로 묶는다.
    const name = /^(keywords\.json|numbers|verdict_summary|summary)$/.test(pre.split(".").pop() || pre) || pre === "" && /keywords/.test(currentFile) ? "*" : k;
    const p = pre ? `${pre}.${name}` : name;
    acc.add(p);
    keys(x, p, acc);
  }
  return acc;
};
let currentFile = "";
const sample = path.join(WEB_ROOT, "sample-data");
const files = [];
const walk = (d, rel = "") => {
  for (const f of fs.readdirSync(d, { withFileTypes: true })) {
    const rp = rel ? `${rel}/${f.name}` : f.name;
    if (f.isDirectory()) walk(path.join(d, f.name), rp);
    else if (f.name.endsWith(".json")) files.push(rp);
  }
};
walk(exp);
let diffs = 0;
for (const f of files) {
  const s = path.join(sample, f);
  if (!fs.existsSync(s)) {
    console.log(`[shape] ${f}: 예시 자료에 이 파일이 없다`);
    continue;
  }
  currentFile = f;
  const a = keys(JSON.parse(fs.readFileSync(path.join(exp, f), "utf-8")));
  const b = keys(JSON.parse(fs.readFileSync(s, "utf-8")));
  const onlyExp = [...a].filter((k) => !b.has(k));
  const onlySample = [...b].filter((k) => !a.has(k));
  if (onlyExp.length) console.log(`[shape] ${f}: 사이트가 아직 모르는 칸(내보내기에만) ${onlyExp.join(", ")}`);
  if (onlySample.length) console.log(`[shape] ${f}: 내보내기가 없앤 칸(예시에만) ${onlySample.join(", ")}`);
  diffs += onlyExp.length + onlySample.length;
}
console.log(`[shape] 비교한 파일 ${files.length}개 · 다른 칸 ${diffs}개 (days/ 는 내보내기가 아직 비워 내므로 비교하지 않는다)`);
fs.rmSync(tmp, { recursive: true, force: true });
