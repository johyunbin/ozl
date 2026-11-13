// 서비스 워커(설계 4-18). 기준 경로 바로 밑(<기준>sw.js)에 두어 scope 가 기준 경로 전체가 되게 한다.
import tpl from "../sw/sw.js?raw";
import { BASE } from "../lib/paths";
import { buildId, KEEP_ISSUES } from "../lib/offline";
export function GET() {
  const body = tpl.replace("__BASE__", BASE).replace("__BUILD__", buildId()).replace("__KEEP__", String(KEEP_ISSUES));
  return new Response(body, { headers: { "Content-Type": "text/javascript; charset=utf-8" } });
}
