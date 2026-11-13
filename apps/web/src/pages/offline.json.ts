// 서비스 워커가 연결될 때마다 받는 "지금 살아 있는 판" 목록과 내림 목록(설계 4-18).
import { loadSite } from "../lib/data";
import { liveList } from "../lib/offline";
export function GET() {
  return new Response(JSON.stringify(liveList(loadSite())), { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
