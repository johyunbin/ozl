// 키워드 모음의 머리 묶음(설계 1-8). 초성(ㄱ ㄴ ㄷ …), 영문 A–Z, 숫자 0–9, 그 밖 순서. 키워드 목록 쪽과 머리별 쪽이 함께 쓴다.
import type { Keyword, Site } from "./data";

const CHO = ["ㄱ", "ㄱ", "ㄴ", "ㄷ", "ㄷ", "ㄹ", "ㅁ", "ㅂ", "ㅂ", "ㅅ", "ㅅ", "ㅇ", "ㅈ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"];
function head(k: string): string {
  const c = k.trim().charAt(0);
  const code = c.charCodeAt(0);
  if (code >= 0xac00 && code <= 0xd7a3) return CHO[Math.floor((code - 0xac00) / 588)];
  if (/[a-z]/i.test(c)) return c.toUpperCase();
  if (/[0-9]/.test(c)) return "0–9";
  return "그 밖";
}
const rank = (h: string) => (/^[ㄱ-ㅎ]$/.test(h) ? 0 : /^[A-Z]$/.test(h) ? 1 : h === "0–9" ? 2 : 3);

/** 한 쪽에 모두 싣는 키워드 수의 상한. 넘으면 키워드 목록 쪽은 머리마다 일부만 싣고 머리별 쪽으로 잇는다. */
export const KW_ONE_PAGE = 300;
/** 나눠 실을 때 머리마다 목록 쪽에 보이는 수(기록이 많은 순). */
export const KW_PER_HEAD = 12;

export type KwGroup = { head: string; n: number; items: [string, Keyword][] };

export function keywordGroups(site: Site): KwGroup[] {
  const list = [...site.keywords.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name, "ko"));
  const groups = new Map<string, [string, Keyword][]>();
  for (const e of list) {
    const h = head(e[1].name);
    if (!groups.has(h)) groups.set(h, []);
    groups.get(h)!.push(e);
  }
  return [...groups.keys()]
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b, "ko"))
    .map((h, i) => ({ head: h, n: i + 1, items: groups.get(h)! }));
}

export const recordCount = (site: Site, k: Keyword) => k.issues.filter((s) => site.issues.has(s)).length;
