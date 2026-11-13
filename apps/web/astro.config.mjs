import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "astro/config";
import { basePath, buildMode, outDir, WEB_ROOT } from "./scripts/paths.mjs";

const mode = buildMode();

// 자료 읽기(src/lib/data.ts)가 남긴 경고를 빌드 끝에 모아 센다.
const warningsSummary = {
  name: "ozl-warnings",
  hooks: {
    "astro:build:done": () => {
      const f = path.join(WEB_ROOT, ".astro", "ozl-warnings.json");
      let list = [];
      try {
        list = JSON.parse(fs.readFileSync(f, "utf-8"));
      } catch {}
      console.log(`[ozl] ${mode === "public" ? "공개용" : "미리보기용"} 빌드 · 자료 경고 ${list.length}건`);
      for (const w of list) console.log(`[ozl] 경고: ${w}`);
    },
  },
};

export default defineConfig({
  base: basePath(mode),
  outDir: outDir(mode),
  trailingSlash: "always",
  build: { format: "directory" },
  integrations: [warningsSummary],
  devToolbar: { enabled: false },
});
