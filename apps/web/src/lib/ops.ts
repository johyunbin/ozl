// 미리보기의 "운영 정보" 상자에 모을 문장(설계 1-12). 공개용 빌드에서는 빈 목록이다.
// 독자 화면(본문)에는 작업 상태, 수집 실패, 정리 전 빈 항목, 공개에서 빠지는 항목을 그리지 않고 여기에만 모은다.
import type { Site, Topics, TopicItem } from "./data";
import { rowById } from "./data";
import { IS_PREVIEW } from "./mode";

/** 화제 목록(첫 화면, 날짜 쪽)의 운영 정보. shown 은 화면에 그릴 항목(visibleTopics 결과). */
export function topicOps(site: Site, t: Topics | null, shown: TopicItem[]): string[] {
  if (!IS_PREVIEW || !t) return [];
  const out: string[] = [];
  if (t.line.source_kinds_failed.length) out.push(`수집 실패: ${t.line.source_kinds_failed.join(", ")} (나머지 출처로 점수를 냈다)`);
  const pending = shown.filter((it) => it.type === "keyword" || !(rowById(site, it.issue_id) && site.issues.has(rowById(site, it.issue_id)!.slug)));
  const names = pending.map((it) => (it.type === "keyword" ? it.keyword : it.keyword)).filter(Boolean);
  if (names.length) out.push(`정리 전이라 목록에서 뺀 화제 ${names.length}건: ${names.join(", ")}`);
  const states = new Map<string, string[]>();
  for (const it of shown) {
    if (it.type !== "issue") continue;
    const row = rowById(site, it.issue_id);
    if (!row || !site.issues.has(row.slug) || !row.publish_state || row.publish_state === "게시") continue;
    states.set(row.publish_state, [...(states.get(row.publish_state) ?? []), row.title]);
  }
  for (const [st, titles] of states) out.push(`${st} ${titles.length}건: ${titles.join(" / ")}`);
  const ex = new Map<string, number>();
  for (const p of t.pre) if (p.excluded.length) ex.set(p.excluded.join(", "), (ex.get(p.excluded.join(", ")) ?? 0) + 1);
  for (const [why, n] of ex) out.push(`공개에서 빠지는 항목(${why}) ${n}건 — 제목과 출처는 미리보기에서도 그리지 않는다`);
  return out;
}

/** 독자에게 그릴 화제 줄: 공개 기록이 있는 이슈만(정리 전 빈 항목은 뺀다). */
export function readerTopics(site: Site, items: TopicItem[]): TopicItem[] {
  return items.filter((it) => {
    if (it.type !== "issue") return false;
    const row = rowById(site, it.issue_id);
    return !!row && site.issues.has(row.slug);
  });
}

const KINDS: Record<string, string> = { claims: "주장", facts: "사실", flow: "흐름", stances: "입장", figures: "그림", open_questions: "남은 질문" };
const RX = /\b(claims|facts|flow|stances|figures|open_questions)\.[a-z]\d+/g;

/** 이슈 화면(최신판)의 운영 정보: 작업 상태, 공개 기준으로 뺀 항목, 검사 경고, 승인 전 화제 추이. 고정판은 없다. */
export function issueOps(is: import("./data").Issue, b: import("./data").Body, fixed: boolean, trendDraft: boolean): string[] {
  if (!IS_PREVIEW || fixed) return [];
  const out: string[] = [];
  const it = b.internal;
  if (it?.publish_state) out.push(it.publish_state === "게시" ? "작업 상태: 게시(게시된 판과 같은 작업본)" : `작업 상태: ${it.publish_state}`);
  if (it?.hidden.length) {
    const by = it.hidden.reduce<Record<string, number>>((a, h) => { const k = h.split(".")[0]; a[k] = (a[k] || 0) + 1; return a; }, {});
    out.push(`공개 기준으로 뺀 항목: ${Object.entries(by).map(([k, n]) => `${KINDS[k] ?? "항목"} ${n}건`).join(", ")}`);
  }
  for (const e of it?.errors ?? []) out.push(`검사 오류: ${e.replace(RX, (m) => KINDS[m.split(".")[0]] ?? "항목")}`);
  for (const w of it?.warnings ?? []) out.push(`검사 경고: ${w.replace(RX, (m) => KINDS[m.split(".")[0]] ?? "항목")}`);
  if (trendDraft) out.push("화제 추이는 작업본 기준 값이다(승인 전)");
  void is;
  return out;
}
