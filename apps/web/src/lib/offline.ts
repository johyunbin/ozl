// 홈 화면 추가와 최근 판 저장(설계 4-18). 빌드 식별자와 "지금 살아 있는 판" 목록을 만든다.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { Site } from "./data";
import { revNumbers } from "./data";

/** 서비스 워커가 저장하는 이슈 수(가장 최근에 본 것부터). */
export const KEEP_ISSUES = 20;

let cached = "";
/**
 * 빌드 식별자. OZL_BUILD_ID 가 있으면 그것, 없으면 자료 폴더의 모든 파일 내용과 이 저장 규칙 판(SW_RULES)의 해시 앞 12자.
 * 자료가 같으면 같은 값이라, 같은 자료로 다시 빌드해도 기기의 저장분을 버리지 않는다.
 */
export const SW_RULES = 1;
export function buildId(): string {
  if (cached) return cached;
  if (process.env.OZL_BUILD_ID) return (cached = process.env.OZL_BUILD_ID.replace(/[^A-Za-z0-9._-]/g, "").slice(0, 40) || "x");
  const root = path.resolve(process.env.OZL_SITE_DATA || path.join(process.cwd(), "sample-data"));
  const h = crypto.createHash("sha256").update(`rules:${SW_RULES}\n`);
  const walk = (d: string) => {
    if (!fs.existsSync(d)) return;
    for (const f of fs.readdirSync(d).sort()) {
      const p = path.join(d, f);
      const st = fs.statSync(p);
      if (st.isDirectory()) walk(p);
      else if (f.endsWith(".json")) h.update(path.relative(root, p)).update("\0").update(fs.readFileSync(p)).update("\0");
    }
  };
  walk(root);
  return (cached = h.digest("hex").slice(0, 12));
}

/**
 * 서비스 워커가 연결될 때마다 받는 목록(offline.json). 여기에 없는 이슈와 판의 저장분은 지운다.
 * 내린 이슈는 내보내기에서 빠져 이 목록에도 없다(이슈 번호를 싣지 않는다 — 주소만).
 */
export function liveList(site: Site) {
  const issues: Record<string, { rev: number | null; revs: number[] }> = {};
  for (const is of site.issues.values()) {
    issues[is.slug] = { rev: is.latest.rev, revs: revNumbers(is).filter((r) => !is.takenDown.has(r)) };
  }
  const takedowns: { slug: string; rev: number | null }[] = [];
  for (const t of site.takedowns) {
    const is = [...site.issues.values()].find((x) => x.latest.id === t.id);
    if (is) takedowns.push({ slug: is.slug, rev: t.rev });
  }
  return { build: buildId(), made_at: site.meta.made_at, keep: KEEP_ISSUES, issues, takedowns };
}
