// 자료 읽기는 이 파일 한 곳에서 한다(설계 2-4).
// 칸마다 기본값을 채우고, 꼴이 다른 칸은 경고로 센다. 공개용에서 판정 값이 넷 밖이거나
// 공개 제외 항목이 오거나 슬러그·날짜 꼴이 어긋나면 경고가 아니라 실패로 멈춘다.
// 공개용에서는 internal, publish_state, trend_now 를 아예 읽어 들이지 않는다.
import fs from "node:fs";
import path from "node:path";
import { IS_PUBLIC } from "./mode";
import { setReferenceYear, parseTime } from "./format";
import { emptySummary, isVerdict, VERDICTS, type Summary } from "./verdicts";
import { keywordSlug } from "./paths";

// ---------- 꼴 ----------
export type Source = { kind: string; by: string; title: string; url: string; checked_at: string };
export type History = { rev: number | null; at: string; from: string; to: string; why: string };
/** basis: 그 판정을 받치는 확인된 사실 문장(선택 칸 — 내보내기가 아직 싣지 않으면 빈 목록). */
export type Part = { gist: string; core: boolean; verdict: string; reasons: string[]; would_decide: string; sources: Source[]; basis: string[] };
export type Claim = {
  id: string; gist: string; kind: string; verdict: string; evidence_label: string; searched: string; not_found: string;
  reasons: string[]; would_decide: string; party_position: string; parts: Part[]; sources: Source[]; history: History[]; basis: string[];
};
export type Group = { verdict: string; note: string; claims: Claim[] };
export type Fact = { text: string; type: string; sources: Source[] };
export type FlowItem = { event_date: string; report_date: string; what: string; kind: string; sources: Source[] };
export type Stance = { who: string; kind: string; summary: string; at: string; sources: Source[] };
export type Correction = { rev: number | null; at: string; kind: string; before: string; after: string; why: string; slug: string; id: string };
export type Trend = { score: number | null; bars7: number[]; asof: string; formula_version: number | null };
export type Figure = { kind: string; caption: string; alt: string };
export type Internal = { publish_state: string; hidden: string[]; errors: string[]; warnings: string[] };
export type Body = {
  id: string; slug: string; rev: number | null; rev_at: string; example: boolean; title: string; rev_line: string;
  what_new: string; why_matters: string; so_far: string[]; reason: string; category: string; keywords: string[];
  aliases: string[]; masked: string; corrections_top: Correction[];
  verdicts: { groups: Group[]; hidden_claims: number; summary: Summary };
  facts: Fact[]; flow: FlowItem[]; stances: Stance[]; open_questions: string[];
  spillover: { issues: string[]; similar_cases: { text: string; url: string }[] };
  figures: Figure[]; sources: Source[]; corrections: Correction[]; ai_notice: string;
  trend: Trend | null; trend_now: Trend | null; internal: Internal | null;
};
export type IndexRow = {
  id: string; slug: string; title: string; topic_state: string; rev: number | null; rev_at: string; rev_line: string;
  verdict_summary: Summary; hidden_claims: number; example: boolean; category: string; keywords: string[]; publish_state: string;
};
export type TopicItem =
  | { type: "issue"; issue_id: string; status_line: string; verdict_summary: Summary; hidden_claims: number; own_counts: boolean; keyword: string }
  | { type: "keyword"; keyword: string; state: string };
export type PreItem = { keyword: string; desc: string; links: { outlet: string; url: string }[]; flags: string[]; excluded: string[] };
export type Topics = {
  line: { updated_at: string; source_kinds_ok: string[]; source_kinds_failed: string[] };
  new: TopicItem[]; ongoing: TopicItem[]; upcoming: { date: string; what: string; url: string }[]; pre: PreItem[];
  empty_note: { new: string; ongoing: string; upcoming: string; pre: string };
};
export type DayRecord = { slug: string; title: string; rev: number | null; verdict_summary: Summary };
export type Day = {
  date: string; topics: Topics | null; records: DayRecord[];
  restored: { label: string; items: { rank: number | null; article: string; views: number | null }[] } | null;
};
export type Keyword = { name: string; names: string[]; issues: string[]; dates: string[]; first_seen: string; related: string[] };
export type Meta = { schema: number | null; mode: string; made_at: string; report_contact: string; test: boolean };
export type Issue = { slug: string; latest: Body; revs: Map<number, Body>; takenDown: Set<number> };
export type Site = {
  meta: Meta; index: IndexRow[]; issues: Map<string, Issue>; days: Map<string, Day>; keywords: Map<string, Keyword>;
  corrections: Correction[]; takedowns: { id: string; rev: number | null; at: string }[]; aliases: Record<string, string[]>;
  warnings: string[];
};

/**
 * 자료에서 온 주소를 href 에 넣어도 되는지. http://, https:// 로 시작하는 것만 돌려주고 나머지(javascript:, data:, 상대 경로 등)는 undefined.
 * 화면은 undefined 면 링크 없이 글자로만 그린다.
 */
export function safeHref(u: string | undefined | null): string | undefined {
  if (typeof u !== "string") return undefined;
  const t = u.trim();
  if (!/^https?:\/\/[^\s]/i.test(t)) return undefined;
  try {
    const x = new URL(t);
    return x.protocol === "http:" || x.protocol === "https:" ? t : undefined;
  } catch {
    return undefined;
  }
}

export const EXCLUDE_FLAGS = ["개인", "사생활", "범죄 의혹", "선거 판세"];
const SLUG_RE = /^[a-z0-9]+(-[a-z0-9]+){0,7}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

// ---------- 경고와 실패 ----------
const warnings: string[] = [];
function warn(msg: string) {
  warnings.push(msg);
}
/** 공개용이면 실패, 미리보기면 경고. */
function strict(msg: string) {
  if (IS_PUBLIC) throw new Error(`[ozl] 공개용 빌드를 멈춘다: ${msg}`);
  warn(msg);
}

// ---------- 칸 읽기 ----------
type O = Record<string, unknown>;
const isObj = (v: unknown): v is O => typeof v === "object" && v !== null && !Array.isArray(v);

function str(o: O, k: string, where: string): string {
  const v = o[k];
  if (v === undefined || v === null) return "";
  if (typeof v === "string") return v;
  if (typeof v === "number") return String(v);
  warn(`${where}: ${k} 가 문자열이 아니다`);
  return "";
}
function n(o: O, k: string, where: string): number | null {
  const v = o[k];
  if (v === undefined || v === null || v === "") return null;
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v)) return Number(v);
  warn(`${where}: ${k} 가 숫자가 아니다`);
  return null;
}
function bool(o: O, k: string): boolean {
  return o[k] === true;
}
function arr(o: O, k: string, where: string): unknown[] {
  const v = o[k];
  if (v === undefined || v === null) return [];
  if (Array.isArray(v)) return v;
  warn(`${where}: ${k} 가 목록이 아니다`);
  return [];
}
function objs(o: O, k: string, where: string): O[] {
  return arr(o, k, where).filter((x, i) => {
    if (isObj(x)) return true;
    warn(`${where}: ${k}[${i}] 가 사전이 아니다`);
    return false;
  }) as O[];
}
function strs(o: O, k: string, where: string): string[] {
  return arr(o, k, where).filter((x) => typeof x === "string" && x.trim() !== "") as string[];
}
function sub(o: O, k: string, where: string): O {
  const v = o[k];
  if (v === undefined || v === null) return {};
  if (isObj(v)) return v;
  warn(`${where}: ${k} 가 사전이 아니다`);
  return {};
}
function verdict(o: O, k: string, where: string): string {
  const v = o[k];
  if (isVerdict(v)) return v;
  strict(`${where}: 판정 값 "${String(v ?? "")}" 이 넷(${VERDICTS.join(", ")}) 밖이다`);
  return "";
}
function summary(o: O, k: string, where: string): Summary {
  const s = emptySummary();
  const v = sub(o, k, where);
  for (const key of Object.keys(v)) {
    if (!isVerdict(key)) {
      strict(`${where}: ${k} 에 넷 밖의 판정 "${key}" 가 있다`);
      continue;
    }
    s[key] = n(v, key, `${where}.${k}`) ?? 0;
  }
  return s;
}
function dateStr(o: O, k: string, where: string): string {
  const v = str(o, k, where);
  if (v && !parseTime(v)) strict(`${where}: ${k} "${v}" 를 시각으로 읽을 수 없다`);
  return v;
}

// ---------- JSON 파일 ----------
let ROOT = "";
function readJson(rel: string): unknown {
  const f = path.join(ROOT, rel);
  if (!fs.existsSync(f)) return undefined;
  try {
    return JSON.parse(fs.readFileSync(f, "utf-8"));
  } catch (e) {
    warn(`${rel}: JSON 으로 읽지 못했다 (${(e as Error).message})`);
    return undefined;
  }
}

// ---------- 본문 ----------
function source(o: O, w: string): Source {
  return { kind: str(o, "kind", w), by: str(o, "by", w), title: str(o, "title", w), url: safeHref(str(o, "url", w)) ?? "", checked_at: str(o, "checked_at", w) };
}
const sources = (o: O, w: string) => objs(o, "sources", w).map((s, i) => source(s, `${w}.sources[${i}]`));

function history(o: O, w: string): History {
  const from = str(o, "from", w);
  const to = str(o, "to", w);
  for (const [k, v] of [["from", from], ["to", to]] as const) if (v && !isVerdict(v)) strict(`${w}: ${k} 판정 "${v}" 가 넷 밖이다`);
  return { rev: n(o, "rev", w), at: str(o, "at", w), from, to, why: str(o, "why", w) };
}

function claim(o: O, w: string): Claim {
  return {
    id: str(o, "id", w), gist: str(o, "gist", w), kind: str(o, "kind", w), verdict: verdict(o, "verdict", w),
    evidence_label: str(o, "evidence_label", w), searched: str(o, "searched", w), not_found: str(o, "not_found", w),
    reasons: strs(o, "reasons", w), would_decide: str(o, "would_decide", w), party_position: str(o, "party_position", w),
    parts: objs(o, "parts", w).map((p, i) => {
      const pw = `${w}.parts[${i}]`;
      return { gist: str(p, "gist", pw), core: bool(p, "core"), verdict: verdict(p, "verdict", pw), reasons: strs(p, "reasons", pw),
        would_decide: str(p, "would_decide", pw), sources: sources(p, pw), basis: strs(p, "basis", pw) };
    }),
    sources: sources(o, w),
    history: objs(o, "history", w).map((h, i) => history(h, `${w}.history[${i}]`)),
    basis: strs(o, "basis", w),
  };
}

function correction(o: O, w: string, slug = ""): Correction {
  return { rev: n(o, "rev", w), at: str(o, "at", w), kind: str(o, "kind", w), before: str(o, "before", w), after: str(o, "after", w),
    why: str(o, "why", w), slug: str(o, "slug", w) || slug, id: str(o, "id", w) };
}

function trend(v: unknown, w: string): Trend | null {
  if (v === undefined || v === null) return null;
  if (!isObj(v)) {
    warn(`${w}: 사전이 아니다`);
    return null;
  }
  const bars = arr(v, "bars7", w).map((x) => (typeof x === "number" && Number.isFinite(x) ? Math.max(0, Math.min(1, x)) : 0));
  return { score: n(v, "score", w), bars7: bars, asof: str(v, "asof", w), formula_version: n(v, "formula_version", w) };
}

function body(raw: unknown, file: string): Body | null {
  if (!isObj(raw)) {
    warn(`${file}: 본문이 사전이 아니다`);
    return null;
  }
  const w = file;
  const slug = str(raw, "slug", w);
  if (!SLUG_RE.test(slug)) {
    strict(`${w}: slug "${slug}" 가 주소 꼴이 아니다`);
    return null;
  }
  const v = sub(raw, "verdicts", w);
  const groups: Group[] = objs(v, "groups", `${w}.verdicts`).map((g, i) => {
    const gw = `${w}.verdicts.groups[${i}]`;
    return { verdict: verdict(g, "verdict", gw), note: str(g, "note", gw), claims: objs(g, "claims", gw).map((c, j) => claim(c, `${gw}.claims[${j}]`)) };
  });
  const sp = sub(raw, "spillover", w);
  const masked = raw["masked"];
  const b: Body = {
    id: str(raw, "id", w), slug, rev: n(raw, "rev", w), rev_at: str(raw, "rev_at", w), example: bool(raw, "example"),
    title: str(raw, "title", w), rev_line: str(raw, "rev_line", w), what_new: str(raw, "what_new", w),
    why_matters: str(raw, "why_matters", w), so_far: strs(raw, "so_far", w), reason: str(raw, "reason", w),
    category: str(raw, "category", w), keywords: strs(raw, "keywords", w), aliases: strs(raw, "aliases", w),
    masked: typeof masked === "string" ? masked : "",
    corrections_top: objs(raw, "corrections_top", w).map((c, i) => correction(c, `${w}.corrections_top[${i}]`, slug)),
    verdicts: { groups, hidden_claims: n(v, "hidden_claims", `${w}.verdicts`) ?? 0, summary: summary(v, "summary", `${w}.verdicts`) },
    facts: objs(raw, "facts", w).map((f, i) => ({ text: str(f, "text", `${w}.facts[${i}]`), type: str(f, "type", `${w}.facts[${i}]`), sources: sources(f, `${w}.facts[${i}]`) })),
    flow: objs(raw, "flow", w).map((f, i) => {
      const fw = `${w}.flow[${i}]`;
      return { event_date: dateStr(f, "event_date", fw), report_date: dateStr(f, "report_date", fw), what: str(f, "what", fw), kind: str(f, "kind", fw), sources: sources(f, fw) };
    }),
    stances: objs(raw, "stances", w).map((s, i) => {
      const sw = `${w}.stances[${i}]`;
      return { who: str(s, "who", sw), kind: str(s, "kind", sw), summary: str(s, "summary", sw), at: str(s, "at", sw), sources: sources(s, sw) };
    }),
    open_questions: objs(raw, "open_questions", w).map((q, i) => str(q, "text", `${w}.open_questions[${i}]`)).filter(Boolean),
    spillover: {
      issues: strs(sp, "issues", `${w}.spillover`),
      similar_cases: objs(sp, "similar_cases", `${w}.spillover`).map((c, i) => ({ text: str(c, "text", `${w}.spillover.similar_cases[${i}]`), url: safeHref(str(c, "url", `${w}.spillover.similar_cases[${i}]`)) ?? "" })).filter((c) => c.text),
    },
    figures: objs(raw, "figures", w).map((g, i) => ({ kind: str(g, "kind", `${w}.figures[${i}]`), caption: str(g, "caption", `${w}.figures[${i}]`), alt: str(g, "alt", `${w}.figures[${i}]`) })),
    sources: sources(raw, w),
    corrections: objs(raw, "corrections", w).map((c, i) => correction(c, `${w}.corrections[${i}]`, slug)),
    ai_notice: str(raw, "ai_notice", w),
    trend: trend(raw["trend"], `${w}.trend`),
    // 공개용에서는 읽어 들이지 않는다(출력 자체가 없게).
    trend_now: IS_PUBLIC ? null : trend(raw["trend_now"], `${w}.trend_now`),
    internal: null,
  };
  if (!IS_PUBLIC && isObj(raw["internal"])) {
    const it = raw["internal"] as O;
    b.internal = { publish_state: str(it, "publish_state", `${w}.internal`), hidden: strs(it, "hidden", `${w}.internal`),
      errors: strs(it, "errors", `${w}.internal`), warnings: strs(it, "warnings", `${w}.internal`) };
  }
  return b;
}

// ---------- 날짜 ----------
function topicItem(o: O, w: string): TopicItem | null {
  if (typeof o["issue_id"] === "string" && o["issue_id"]) {
    return { type: "issue", issue_id: o["issue_id"] as string, status_line: str(o, "status_line", w),
      verdict_summary: summary(o, "verdict_summary", w), hidden_claims: n(o, "hidden_claims", w) ?? 0,
      // 그날 목록이 승인될 때의 수. 칸이 있으면 index 의 지금 값보다 먼저 쓴다.
      own_counts: isObj(o["verdict_summary"]), keyword: typeof o["keyword"] === "string" ? (o["keyword"] as string).trim() : "" };
  }
  if (typeof o["keyword"] === "string" && o["keyword"]) return { type: "keyword", keyword: o["keyword"] as string, state: str(o, "state", w) || "정리 전" };
  warn(`${w}: 항목이 {issue_id} 도 {keyword} 도 아니다`);
  return null;
}

function day(raw: unknown, file: string, date: string): Day | null {
  if (!isObj(raw)) {
    warn(`${file}: 사전이 아니다`);
    return null;
  }
  const w = file;
  let topics: Topics | null = null;
  if (isObj(raw["topics"])) {
    const t = raw["topics"] as O;
    const line = sub(t, "line", `${w}.topics`);
    const en = sub(t, "empty_note", `${w}.topics`);
    const items = (k: string) =>
      objs(t, k, `${w}.topics`).map((x, i) => topicItem(x, `${w}.topics.${k}[${i}]`)).filter((x): x is TopicItem => x !== null);
    topics = {
      line: { updated_at: str(line, "updated_at", `${w}.line`), source_kinds_ok: strs(line, "source_kinds_ok", `${w}.line`),
        source_kinds_failed: strs(line, "source_kinds_failed", `${w}.line`) },
      new: items("new"), ongoing: items("ongoing"),
      upcoming: objs(t, "upcoming", `${w}.topics`).map((u, i) => {
        const uw = `${w}.topics.upcoming[${i}]`;
        const d = str(u, "date", uw);
        if (d && !DATE_RE.test(d)) strict(`${uw}: 날짜 "${d}" 꼴이 YYYY-MM-DD 가 아니다`);
        return { date: d, what: str(u, "what", uw), url: safeHref(str(u, "url", uw)) ?? "" };
      }).filter((u) => u.what).sort((a, b) => a.date.localeCompare(b.date)),
      pre: objs(t, "pre", `${w}.topics`).map((p, i) => {
        const pw = `${w}.topics.pre[${i}]`;
        const flags = strs(p, "flags", pw);
        const excluded = flags.filter((f) => EXCLUDE_FLAGS.includes(f));
        if (excluded.length && IS_PUBLIC) {
          throw new Error(`[ozl] 공개용 빌드를 멈춘다: ${pw} 에 공개 제외 항목(${excluded.join(", ")})이 있다`);
        }
        return {
          keyword: str(p, "keyword", pw), desc: str(p, "desc", pw), flags, excluded,
          links: objs(p, "links", pw).map((l, j) => ({ outlet: str(l, "outlet", `${pw}.links[${j}]`), url: safeHref(str(l, "url", `${pw}.links[${j}]`)) ?? "" })).filter((l) => l.outlet),
        };
      }).filter((p) => p.keyword),
      empty_note: { new: str(en, "new", w), ongoing: str(en, "ongoing", w), upcoming: str(en, "upcoming", w), pre: str(en, "pre", w) },
    };
  } else if (raw["topics"] !== null && raw["topics"] !== undefined) {
    warn(`${w}: topics 가 사전이 아니다`);
  }
  const records: DayRecord[] = objs(raw, "records", w)
    .map((r, i) => ({ slug: str(r, "slug", `${w}.records[${i}]`), title: str(r, "title", `${w}.records[${i}]`), rev: n(r, "rev", `${w}.records[${i}]`), verdict_summary: summary(r, "verdict_summary", `${w}.records[${i}]`) }))
    .filter((r) => r.slug);
  let restored: Day["restored"] = null;
  if (isObj(raw["restored"])) {
    const r = raw["restored"] as O;
    restored = {
      label: str(r, "label", `${w}.restored`) || "위키백과 조회로 본 그날의 관심 문서",
      items: objs(r, "items", `${w}.restored`).map((x, i) => ({ rank: n(x, "rank", `${w}.restored.items[${i}]`), article: str(x, "article", `${w}.restored.items[${i}]`), views: n(x, "views", `${w}.restored.items[${i}]`) }))
        .filter((x) => x.article).sort((a, b) => (a.rank ?? 1e9) - (b.rank ?? 1e9)),
    };
  }
  if (!topics && !records.length && !restored) return null;
  return { date, topics, records, restored };
}

// ---------- 전부 ----------
let cache: Site | null = null;

export function loadSite(): Site {
  if (cache) return cache;
  ROOT = path.resolve(process.env.OZL_SITE_DATA || path.join(process.cwd(), "sample-data"));
  if (!fs.existsSync(ROOT)) warn(`자료 폴더 ${ROOT} 가 없다 — 빈 사이트를 만든다`);

  const mraw = readJson("meta.json");
  const m = isObj(mraw) ? mraw : {};
  const meta: Meta = { schema: n(m, "schema", "meta.json"), mode: str(m, "mode", "meta.json"), made_at: str(m, "made_at", "meta.json"),
    report_contact: str(m, "report_contact", "meta.json"), test: bool(m, "test") };
  setReferenceYear(parseTime(meta.made_at)?.y ?? null);

  // index.json
  const iraw = readJson("index.json");
  const index: IndexRow[] = (isObj(iraw) ? objs(iraw, "issues", "index.json") : []).map((r, i) => {
    const w = `index.json issues[${i}]`;
    const slug = str(r, "slug", w);
    if (!SLUG_RE.test(slug)) strict(`${w}: slug "${slug}" 가 주소 꼴이 아니다`);
    return {
      id: str(r, "id", w), slug, title: str(r, "title", w), topic_state: str(r, "topic_state", w), rev: n(r, "rev", w),
      rev_at: str(r, "rev_at", w), rev_line: str(r, "rev_line", w), verdict_summary: summary(r, "verdict_summary", w),
      hidden_claims: n(r, "hidden_claims", w) ?? 0, example: bool(r, "example"), category: str(r, "category", w),
      keywords: strs(r, "keywords", w), publish_state: IS_PUBLIC ? "" : str(r, "publish_state", w),
    };
  }).filter((r) => SLUG_RE.test(r.slug));

  // takedowns.json
  const traw = readJson("takedowns.json");
  const takedowns = (Array.isArray(traw) ? traw.filter(isObj) : []).map((t, i) => ({ id: str(t, "id", `takedowns[${i}]`), rev: n(t, "rev", `takedowns[${i}]`), at: str(t, "at", `takedowns[${i}]`) }));

  // issues/
  const issues = new Map<string, Issue>();
  for (const row of index) {
    const latest = body(readJson(`issues/${row.slug}.json`), `issues/${row.slug}.json`);
    if (!latest) {
      warn(`issues/${row.slug}.json: 본문이 없어 이슈 화면을 만들지 않는다`);
      continue;
    }
    const revs = new Map<number, Body>();
    const rdir = path.join(ROOT, "issues", row.slug, "r");
    if (fs.existsSync(rdir)) {
      for (const f of fs.readdirSync(rdir)) {
        const mm = f.match(/^(\d+)\.json$/);
        if (!mm) continue;
        const b = body(readJson(`issues/${row.slug}/r/${f}`), `issues/${row.slug}/r/${f}`);
        if (b) revs.set(Number(mm[1]), b);
      }
    }
    const takenDown = new Set(takedowns.filter((t) => t.id === latest.id && t.rev !== null).map((t) => t.rev as number));
    issues.set(row.slug, { slug: row.slug, latest, revs, takenDown });
  }

  // days/
  const days = new Map<string, Day>();
  const ddir = path.join(ROOT, "days");
  if (fs.existsSync(ddir)) {
    for (const f of fs.readdirSync(ddir).sort()) {
      if (!f.endsWith(".json")) continue;
      const date = f.slice(0, -5);
      if (!DATE_RE.test(date) || !parseTime(date)) {
        strict(`days/${f}: 파일 이름이 날짜 꼴(YYYY-MM-DD)이 아니다`);
        continue;
      }
      const d = day(readJson(`days/${f}`), `days/${f}`, date);
      if (d) days.set(date, d);
    }
  }

  // keywords.json — 같은 주소가 되는 키워드는 한 쪽으로 합친다.
  const kraw = readJson("keywords.json");
  const kws = new Map<string, Keyword>();
  if (isObj(kraw)) {
    for (const [name, v] of Object.entries(kraw)) {
      if (!isObj(v)) {
        warn(`keywords.json: ${name} 가 사전이 아니다`);
        continue;
      }
      const ks = keywordSlug(name);
      if (!ks) continue;
      const w = `keywords.json ${name}`;
      const k: Keyword = { name, names: [name], issues: strs(v, "issues", w), dates: strs(v, "dates", w).filter((d) => DATE_RE.test(d)),
        first_seen: str(v, "first_seen", w), related: strs(v, "related", w) };
      const prev = kws.get(ks);
      if (prev) {
        warn(`keywords.json: "${prev.name}" 와 "${name}" 가 같은 주소 k/${ks}/ 가 되어 한 쪽으로 합쳤다`);
        prev.issues = [...new Set([...prev.issues, ...k.issues])];
        prev.dates = [...new Set([...prev.dates, ...k.dates])].sort();
        prev.related = [...new Set([...prev.related, ...k.related])];
        if (!prev.first_seen || (k.first_seen && k.first_seen < prev.first_seen)) prev.first_seen = k.first_seen;
        prev.names.push(name);
      } else kws.set(ks, k);
    }
  }

  // corrections.json
  const craw = readJson("corrections.json");
  const corrections = (isObj(craw) ? objs(craw, "items", "corrections.json") : []).map((c, i) => correction(c, `corrections.json items[${i}]`));

  // aliases.json(검색 별칭)
  const araw = readJson("aliases.json");
  const aliases: Record<string, string[]> = {};
  if (isObj(araw)) for (const [k, v] of Object.entries(araw)) if (Array.isArray(v)) aliases[k] = v.filter((x) => typeof x === "string");

  // 옛 주소가 지금 이슈의 주소와 같으면 만들지 않는다.
  for (const is of issues.values()) {
    for (const a of is.latest.aliases) if (issues.has(a)) warn(`${is.slug}: 옛 주소 ${a} 가 지금 있는 이슈의 주소와 같아 안내 쪽을 만들지 않는다`);
  }

  cache = { meta, index, issues, days, keywords: kws, corrections, takedowns, aliases, warnings };
  try {
    const dir = path.join(process.cwd(), ".astro");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "ozl-warnings.json"), JSON.stringify(warnings, null, 1));
  } catch {}
  return cache;
}

// ---------- 고르기 ----------
export function rowById(site: Site, id: string): IndexRow | undefined {
  return site.index.find((r) => r.id === id);
}
export function rowBySlug(site: Site, slug: string): IndexRow | undefined {
  return site.index.find((r) => r.slug === slug);
}

/** 화제 추이 값(설계 2-6). */
export function pickTrend(is: Issue, b: Body, fixed: boolean): { trend: Trend | null; draft: boolean } {
  if (fixed) return { trend: b.trend, draft: false };
  const same = b.rev !== null ? is.revs.get(b.rev) : undefined;
  if (same?.trend) return { trend: same.trend, draft: false };
  if (b.trend) return { trend: b.trend, draft: false };
  if (!IS_PUBLIC && b.trend_now) return { trend: b.trend_now, draft: true };
  return { trend: null, draft: false };
}

/** 첫 화면이 보여 줄 날: topics 가 있는 가장 늦은 날. */
export function latestTopicDay(site: Site): Day | undefined {
  return [...site.days.values()].filter((d) => d.topics).sort((a, b) => b.date.localeCompare(a.date))[0];
}

export function sortedDates(site: Site): string[] {
  return [...site.days.keys()].sort();
}

export function months(site: Site): string[] {
  return [...new Set(sortedDates(site).map((d) => d.slice(0, 7)))].sort();
}

/** 고정판 번호(오름차순). */
export function revNumbers(is: Issue): number[] {
  return [...is.revs.keys()].sort((a, b) => a - b);
}

/**
 * 화제 목록에 그릴 항목만 남긴다(계획 4-2-3). issue 항목은 공개한 기록이 있을 때만 그린다.
 * 기록이 없는 issue 항목은 공개용에서는 늘 빼고, 미리보기에서는 키워드가 있을 때만 "정리 전"으로 그린다.
 * 지어낸 제목으로 채우지 않는다. 뺀 항목은 빌드 경고 한 줄로 남긴다.
 */
export function visibleTopics(site: Site, items: TopicItem[], preview: boolean, where: string): TopicItem[] {
  return items.filter((it) => {
    if (it.type === "keyword") return !!it.keyword;
    const row = rowById(site, it.issue_id);
    if (row && site.issues.has(row.slug)) return true;
    if (preview && it.keyword) return true;
    console.warn(`[site] ${where}: 공개 기록이 없는 화제 ${it.issue_id} 를 목록에서 뺐다`);
    return false;
  });
}
