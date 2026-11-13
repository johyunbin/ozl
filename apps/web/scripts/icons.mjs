// 홈 화면 아이콘 PNG 를 public/icons/icon.svg 에서 다시 그린다(192, 512). 남의 그림을 쓰지 않는다.
// 쓰는 법(apps/web 에서): npm run icons
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (!process.env.PLAYWRIGHT_BROWSERS_PATH) process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(WEB_ROOT, ".pw-browsers");
const { chromium } = await import("playwright");
const dir = path.join(WEB_ROOT, "public/icons");
const svg = fs.readFileSync(path.join(dir, "icon.svg"), "utf-8");
const browser = await chromium.launch();
try {
  for (const size of [192, 512]) {
    const page = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    await page.setContent(`<html><body style="margin:0">${svg.replace(/width="512" height="512"/, `width="${size}" height="${size}"`)}</body></html>`);
    await page.locator("svg").screenshot({ path: path.join(dir, `icon-${size}.png`) });
    await page.close();
    console.log(`[icons] icon-${size}.png`);
  }
} finally {
  await browser.close();
}
