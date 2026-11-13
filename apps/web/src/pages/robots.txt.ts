// 미리보기면 전부 막는다(설계 2-2).
import { IS_PREVIEW } from "../lib/mode";
export function GET() {
  const body = IS_PREVIEW ? "User-agent: *\nDisallow: /\n" : "User-agent: *\nAllow: /\n";
  return new Response(body, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
