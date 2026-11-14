// 글(읽는 층) 화면에 쓰는 작은 도움 함수(명세 2절, 6절).
import type { Article, ArtNews, Site } from "./data";
import { parseTime } from "./format";

const esc = (t: string) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** 출처 줄의 id. 본문의 [^n] 이 이리로 간다. */
export const srcId = (n: number) => `src-${n}`;

/**
 * 본문 글의 [^n] 을 위 첨자 링크로 바꾼 HTML. 나머지 글은 모두 이스케이프한다.
 * 이어진 각주([^1][^2])는 위 첨자 하나에 쉼표로 잇는다. 출처에 없는 번호는 링크 없이 번호만 둔다.
 */
export function withNotes(text: string, known: Set<number>): string {
  const parts = text.split(/((?:\[\^\d+\])+)/);
  return parts
    .map((p, i) => {
      if (i % 2 === 0) return esc(p);
      const ns = [...p.matchAll(/\[\^(\d+)\]/g)].map((m) => Number(m[1]));
      const inner = ns
        .map((n) => (known.has(n) ? `<a href="#${srcId(n)}" aria-label="출처 ${n}">${n}</a>` : `<span>${n}</span>`))
        .join('<span class="fn-sep">,</span>');
      return `<sup class="fn">${inner}</sup>`;
    })
    .join("");
}

/** 각주 표시를 뺀 글(첫 화면의 짧은 줄, description). */
export function plain(text: string): string {
  return text.replace(/\[\^\d+\]/g, "").replace(/\s+/g, " ").trim();
}

export function sourceNumbers(a: Article): Set<number> {
  return new Set(a.sources.map((s) => s.n));
}

const NATIVE = ["하루", "이틀", "사흘", "나흘", "닷새", "엿새", "이레"];

/** started 부터 as_of 까지 며칠째인지(시작한 날이 1). 못 읽으면 null. */
export function dayNumber(started: string, asOf: string): number | null {
  const a = parseTime(started);
  const b = parseTime(asOf);
  if (!a || !b) return null;
  const d = Math.round((Date.UTC(b.y, b.m - 1, b.d) - Date.UTC(a.y, a.m - 1, a.d)) / 86400000) + 1;
  return d >= 1 ? d : null;
}

/** "나흘째", 여드레부터는 "8일째". */
export function dayWord(n: number): string {
  return n <= NATIVE.length ? `${NATIVE[n - 1]}째` : `${n}일째`;
}

/** 진행 중이면 "나흘째", 일단락이면 "". */
export function runningLabel(a: Article): string {
  if (a.state !== "진행 중") return "";
  const n = dayNumber(a.started, a.as_of);
  return n ? dayWord(n) : "";
}

/** "11월 14일 오후 9시"(분이 있으면 "오후 9시 30분"). 해가 다르면 해를 붙인다. */
export function fmtAsOf(s: string, refYear: number | null): string {
  const p = parseTime(s);
  if (!p) return "";
  const day = `${refYear !== null && p.y !== refYear ? `${p.y}년 ` : ""}${p.m}월 ${p.d}일`;
  if (!p.hasTime) return day;
  const ap = p.hh < 12 ? "오전" : "오후";
  const h = p.hh % 12 === 0 ? 12 : p.hh % 12;
  return `${day} ${ap} ${h}시${p.mm ? ` ${p.mm}분` : ""}`;
}

/** 날짜 줄 이름. 자료의 label 이 있으면 그것을, 없으면 날짜에서 만든다. */
export function newsLabel(n: ArtNews): string {
  if (n.label) return n.label;
  const p = parseTime(n.date);
  return p ? `${p.m}월 ${p.d}일${n.planned ? " 예정" : ""}` : "";
}

/** 보이는 새 소식은 5개까지(명세 5절). 넘치는 것은 그 전에 있었던 일 앞쪽으로 내린다. */
export const NEWS_MAX = 5;
export function splitNews(a: Article): { shown: ArtNews[]; earlier: ArtNews[] } {
  return { shown: a.news.slice(0, NEWS_MAX), earlier: [...a.news.slice(NEWS_MAX), ...a.earlier] };
}

/** 분야 꼬리표의 첫 마디("사회 · 교육" → "사회"). 첫 화면 칩이 쓴다. */
export function field(category: string): string {
  return category.split(/\s*[·,/]\s*/)[0]?.trim() || category.trim();
}

/** 정렬용 숫자(읽지 못하면 0). */
export function timeKey(s: string): number {
  const p = parseTime(s);
  return p ? Date.UTC(p.y, p.m - 1, p.d, p.hh, p.mm) : 0;
}

/** 글이 있는 이슈를 as_of 최신순으로. */
export function articles(site: Site): { slug: string; a: Article; example: boolean }[] {
  return [...site.issues.values()]
    .filter((is) => is.latest.article)
    .map((is) => ({ slug: is.slug, a: is.latest.article!, example: is.latest.example }))
    .sort((x, y) => timeKey(y.a.as_of) - timeKey(x.a.as_of) || x.slug.localeCompare(y.slug));
}
