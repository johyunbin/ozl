// 결과 폴더에 검색 색인을 만든다(설계 5-1). 같은 버전의 npm 패키지를 쓴다.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { outDir, WEB_ROOT } from "./paths.mjs";

const out = outDir();
const bin = path.join(WEB_ROOT, "node_modules/.bin/pagefind");
const r = spawnSync(bin, ["--site", out], { stdio: "inherit" });
process.exit(r.status ?? 1);
