// 시각, 요일, 호스트. 시각은 모두 한국 시간(KST)으로 읽는다.
const WEEK = ["일", "월", "화", "수", "목", "금", "토"];

export type Parsed = { y: number; m: number; d: number; hh: number; mm: number; hasTime: boolean };

let refYear = new Date().getFullYear();
/** "지금 해"를 자료 만든 시각의 해로 맞춘다(data.ts 가 meta.made_at 으로 부른다). */
export function setReferenceYear(y: number | null) {
  if (y) refYear = y;
}

export function parseTime(s: unknown): Parsed | null {
  if (typeof s !== "string") return null;
  const t = s.trim();
  if (!t) return null;
  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return { y: +m[1], m: +m[2], d: +m[3], hh: 0, mm: 0, hasTime: false };
  m = t.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/);
  if (!m) return null;
  const [y, mo, d, hh, mi] = [+m[1], +m[2], +m[3], +m[4], +m[5]];
  if (!m[6]) return { y, m: mo, d, hh, mm: mi, hasTime: true }; // 시간대 없는 값은 KST 로 본다
  const off = m[6] === "Z" ? 0 : (m[6][0] === "-" ? -1 : 1) * (+m[6].slice(1, 3) * 60 + +m[6].slice(-2));
  const utc = Date.UTC(y, mo - 1, d, hh, mi) - off * 60000;
  const k = new Date(utc + 9 * 3600000);
  return { y: k.getUTCFullYear(), m: k.getUTCMonth() + 1, d: k.getUTCDate(), hh: k.getUTCHours(), mm: k.getUTCMinutes(), hasTime: true };
}

const pad = (n: number) => String(n).padStart(2, "0");

function dayPart(p: Parsed): string {
  return p.y === refYear ? `${p.m}월 ${p.d}일` : `${p.y}년 ${p.m}월 ${p.d}일`;
}

/** "1월 2일" (해가 다르면 "2099년 1월 2일"). 못 읽으면 "". */
export function fmtDate(s: unknown): string {
  const p = parseTime(s);
  return p ? dayPart(p) : "";
}

/** "1월 2일 07:40" (시각이 없으면 날짜만). */
export function fmtDateTime(s: unknown): string {
  const p = parseTime(s);
  if (!p) return "";
  return p.hasTime ? `${dayPart(p)} ${pad(p.hh)}:${pad(p.mm)}` : dayPart(p);
}

/** "07:40". */
export function fmtClock(s: unknown): string {
  const p = parseTime(s);
  return p && p.hasTime ? `${pad(p.hh)}:${pad(p.mm)}` : "";
}

/** 해를 붙이지 않는 짧은 날짜 "1월 2일". */
export function fmtMonthDay(s: unknown): string {
  const p = parseTime(s);
  return p ? `${p.m}월 ${p.d}일` : "";
}

export function weekday(s: unknown): string {
  const p = parseTime(s);
  return p ? WEEK[new Date(Date.UTC(p.y, p.m - 1, p.d)).getUTCDay()] : "";
}

/** "1월 2일 금" */
export function fmtDateWeek(s: unknown): string {
  const d = fmtDate(s);
  return d ? `${d} ${weekday(s)}` : "";
}

export function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

export function num(n: number): string {
  return n.toLocaleString("ko-KR");
}

export const WEEKDAYS = WEEK;
