// 빌드 전 검사(설계 2-3). 종료 코드: 1 자료 형식, 2 신고 칸, 3 자료와 결과 폴더가 맞지 않음.
// 통과하면 결과 폴더를 비운다(지난 빌드의 쪽이 남지 않게).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { OUT_MARK, outDir, PREVIEW_DEFAULT, PUBLIC_DIST, REPO_ROOT, siteData, WEB_ROOT } from "./paths.mjs";

const mode = process.argv[2] === "public" ? "public" : "preview";
const out = outDir(mode);
const data = siteData();
const fail = (code, msg) => {
  console.error(`[guard] ${msg}`);
  process.exit(code);
};
const inside = (p, root) => {
  const r = path.relative(root, p);
  return r === "" || (!r.startsWith("..") && !path.isAbsolute(r));
};

let meta;
try {
  meta = JSON.parse(fs.readFileSync(path.join(data, "meta.json"), "utf-8"));
} catch {
  fail(1, `자료 폴더에 meta.json 이 없거나 형식 판이 다르다 (${data})`);
}
if (!meta || meta.schema !== 1) fail(1, `자료 폴더에 meta.json 이 없거나 형식 판이 다르다 (${data})`);

let hasExample = false;
try {
  const idx = JSON.parse(fs.readFileSync(path.join(data, "index.json"), "utf-8"));
  hasExample = Array.isArray(idx?.issues) && idx.issues.some((r) => r && r.example === true);
} catch {}

if (mode === "public") {
  if (meta.mode === "preview" && meta.test !== true) fail(3, "미리보기용 자료로 공개용 사이트를 만들 수 없다");
  const contact = (process.env.OZL_REPORT_CONTACT || meta.report_contact || "").trim();
  if (!contact) fail(2, "신고 연락처가 비어 있어 공개용 빌드를 멈춘다");
  const proc = path.join(WEB_ROOT, "src/content/report-procedure.md");
  if (!fs.existsSync(proc)) {
    // 처리 절차 글은 아직 쓰지 않았다. 시험 자료(meta.test)로 시험 폴더에 만드는 빌드만 경고로 넘긴다.
    if (meta.test === true && !inside(out, PUBLIC_DIST)) console.warn("[guard] 경고: 신고 처리 절차 글이 없다(시험 빌드라 계속한다)");
    else fail(2, "신고 처리 절차 글이 없다 (src/content/report-procedure.md)");
  }
  if ((meta.test === true || hasExample) && inside(out, PUBLIC_DIST)) fail(3, "시험 자료는 시험 폴더에만 만든다. OZL_WEB_OUT 을 주라");
} else {
  if (inside(out, WEB_ROOT)) fail(3, "미리보기 결과는 저장소 밖(private/out/web_preview)에만 쓴다");
}

// 지우기 전 안전 검사. 결과 폴더가 저장소, 웹 폴더, 홈, 자료 폴더 자신이거나 그것을 품으면 거부한다.
// 이미 있는 폴더는 비었거나, 이 빌드가 남긴 표식(.ozl-web-out)이 있거나, 정해 둔 기본 폴더일 때만 비운다.
const real = (p) => {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
};
const outReal = real(out);
if (outReal === path.parse(outReal).root) fail(3, `결과 폴더가 디스크 맨 위다. 지우지 않는다 (${out})`);
for (const [name, p] of [["저장소", REPO_ROOT], ["웹 폴더", WEB_ROOT], ["홈 폴더", os.homedir()], ["자료 폴더", data], ["지금 폴더", process.cwd()]]) {
  if (inside(real(p), outReal)) fail(3, `결과 폴더가 ${name}이거나 그것을 품는다. 지우지 않는다 (${out})`);
}
if (fs.existsSync(out)) {
  if (!fs.statSync(out).isDirectory()) fail(3, `결과 자리에 폴더가 아닌 것이 있다 (${out})`);
  const entries = fs.readdirSync(out);
  const named = outReal === real(PUBLIC_DIST) || outReal === real(PREVIEW_DEFAULT);
  if (entries.length && !entries.includes(OUT_MARK) && !named) {
    fail(3, `결과 폴더에 이 빌드가 남긴 표식(${OUT_MARK})이 없다. 빈 폴더나 새 폴더를 주라 (${out})`);
  }
}
fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, OUT_MARK), "ozl web build output\n");
console.log(`[guard] ${mode === "public" ? "공개용" : "미리보기용"} · 자료 ${data} · 결과 ${out}`);
