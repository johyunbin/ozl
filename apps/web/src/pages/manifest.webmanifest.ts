// 웹 앱 매니페스트(설계 4-18). 기준 경로(/ 또는 /preview/) 안에서만 앱으로 연다.
import { url } from "../lib/paths";
export function GET() {
  const m = {
    name: "OZL",
    short_name: "OZL",
    description: "그날 화제가 된 일의 주장마다 판정과 근거 출처를 붙인 기록",
    lang: "ko",
    dir: "ltr",
    start_url: url(),
    scope: url(),
    id: url(),
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#ffffff",
    icons: [
      { src: url("icons/icon.svg"), sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: url("icons/icon-192.png"), sizes: "192x192", type: "image/png", purpose: "any" },
      { src: url("icons/icon-512.png"), sizes: "512x512", type: "image/png", purpose: "any" },
      { src: url("icons/icon-512.png"), sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
  return new Response(JSON.stringify(m, null, 1), { headers: { "Content-Type": "application/manifest+json; charset=utf-8" } });
}
