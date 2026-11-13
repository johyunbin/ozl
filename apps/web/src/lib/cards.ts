// 넘겨 보는 카드의 장 나누기(설계 4-17). 화면(카드 보기)과 그림 전용 화면이 같은 장을 쓴다.
//
// 넘침은 화면에서 재지 않고 빌드 때 글자 수로 정한다. 카드 한 장의 크기를 글자 크기(em) 단위로 놓고,
// 덩어리마다 "몇 줄이 되나"를 글자 너비로 어림해 높이를 더한다. 예산을 넘으면 다음 장 "(이어서)" 로 넘긴다.
// 어림은 일부러 넉넉하게 잡는다(한글 한 자 0.95em, 줄 끝에서 낱말째 넘어가는 몫 8%).
// 그림을 찍는 스크립트(scripts/cards.mjs)가 실제로 넘친 상자가 없는지 다시 잰다.
//
// 글은 자료에 있는 문장만 싣는다. 화면이 지어 붙이는 말은 머리 글("무엇이 새로운가" 같은)과 안내 문장뿐이고,
// cards.json 에서 from: "ui" 로 따로 적는다.
import type { Body, Claim, Issue, Site, Source } from "./data";
import { revNumbers } from "./data";
import { fmtDate, host } from "./format";
import { issueUrl, revUrl } from "./paths";
import { emptySummary, sortGroups, summaryTotal, VERDICTS, type Summary } from "./verdicts";

export type Block =
  | { t: "title"; text: string; example: boolean }
  | { t: "meta"; text: string }
  | { t: "summary"; summary: Summary; total: number }
  | { t: "h"; text: string }
  | { t: "p"; text: string; ui?: boolean; small?: boolean }
  | { t: "gist"; text: string; kind: string }
  | { t: "verdict"; verdict: string; past: string; evidence: string }
  | { t: "part"; verdict: string; core: boolean; text: string }
  | { t: "li"; text: string }
  | { t: "src"; by: string; title: string; host: string }
  | { t: "link"; text: string; href: string; shown: string };

export type CardKind = "cover" | "intro" | "claim" | "questions" | "end";
export type Card = { kind: CardKind; label: string; cont: boolean; blocks: Block[]; claimVerdict: string };

export type Deck = {
  slug: string; title: string; rev: number | null; date: string; example: boolean;
  /** 이 판의 고정 주소가 있으면(판 사본이 있으면) 참. */
  fixed: boolean; fixedPath: string; issuePath: string;
  cards: Card[];
};

// ---- 크기(카드 폭 = 22.5em, 높이 = 28.125em) ----
const CARD_W = 22.5;
const PAD = 1.25;
const CONTENT_W = CARD_W - 2 * PAD; // 20em
/** 머리 줄, 꼬리 줄, 안쪽 여백을 뺀 본문 높이(em). 실제 남는 자리는 21.7em(1080 폭에서 1041px)이다. */
export const BODY_BUDGET = 21.5;

// 덩어리 꼴마다 글자 크기(em)와 줄 간격, 위 간격(em). Card.astro 의 CSS 와 맞춘다.
const STYLE: Record<string, { size: number; lh: number; gap: number }> = {
  title: { size: 1.625, lh: 1.3, gap: 0 },
  meta: { size: 0.875, lh: 1.5, gap: 0.5 },
  summary: { size: 1, lh: 1.5, gap: 0.5 },
  h: { size: 0.875, lh: 1.5, gap: 1 },
  p: { size: 1, lh: 1.55, gap: 0.25 },
  psmall: { size: 0.875, lh: 1.5, gap: 0.5 },
  gist: { size: 1.25, lh: 1.4, gap: 0 },
  verdict: { size: 1, lh: 1.5, gap: 0.75 },
  part: { size: 0.9375, lh: 1.5, gap: 0.375 },
  li: { size: 0.9375, lh: 1.5, gap: 0.375 },
  src: { size: 0.875, lh: 1.45, gap: 0.5 },
  link: { size: 0.9375, lh: 1.5, gap: 0.5 },
};

/** 글자 너비 어림(em). 한글과 넓은 글자 0.95, 숫자와 로마자 0.62, 띄어쓰기 0.3, 문장 부호 0.4. */
export function textWidth(s: string): number {
  let w = 0;
  for (const ch of s) {
    const c = ch.codePointAt(0) ?? 0;
    if (ch === " ") w += 0.3;
    else if (/[0-9A-Za-z]/.test(ch)) w += 0.62;
    else if (/[.,:;'"()\[\]·\-/%~!?’‘“”]/.test(ch)) w += 0.4;
    else if (c < 0x2e80) w += 0.7;
    else w += 0.95;
  }
  return w;
}

/** 글 너비 w(그 덩어리 글자 크기의 em)가 몇 줄이 되나. 낱말째 넘어가는 줄 끝 손실을 8% 로 잡는다(keep-all). */
function linesOf(w: number, size: number, lead = 0): number {
  const per = (CONTENT_W - lead) / size;
  return Math.max(1, Math.ceil(w / (per * 0.92)));
}
function lines(text: string, size: number, lead = 0): number {
  return linesOf(textWidth(text), size, lead);
}

/** 덩어리 하나의 높이(em, 위 간격 포함). first 면 위 간격을 빼고 센다. */
export function blockHeight(b: Block, first = false): number {
  const key = b.t === "p" && b.small ? "psmall" : b.t;
  const st = STYLE[key];
  const gap = first ? 0 : st.gap;
  const h = (n: number) => n * st.size * st.lh;
  switch (b.t) {
    // "예시" 꼬리표는 제목보다 작은 글자라 제목 글자로 1.6자 몫이다.
    case "title": return gap + h(linesOf(textWidth(b.text) + (b.example ? 1.6 : 0), st.size));
    case "summary": return gap + 4 * 1.6 + 0.5 * 3;
    case "verdict": {
      // 판정 표시(지난 판정 포함) 한 줄 + 근거 한 줄 이상.
      const head = 1.6; // 테두리 있는 표시는 조금 더 높다
      return gap + head + (b.evidence ? h(lines(`근거: ${b.evidence}`, st.size)) : 0);
    }
    // 판정 표시(모양 1.3em + 글자)와 "핵심" 꼬리표가 같은 줄 앞에 붙는다.
    case "part": return gap + h(linesOf(textWidth(b.verdict) + 1.3 + (b.core ? 2.4 : 0) + textWidth(b.text), st.size));
    case "li": return gap + h(lines(b.text, st.size, 1));
    case "src": return gap + h(lines(b.title ? `${b.by} · ${b.title}` : b.by, st.size)) + (b.host ? 0.8125 * 1.45 : 0); // 호스트 줄
    case "link": return gap + h(lines(b.text, st.size)) + h(lines(b.shown, 0.8125)) * 0.87;
    case "gist": return gap + h(lines((b.kind ? `${b.kind}  ` : "") + b.text, st.size));
    default: return gap + h(lines((b as { text: string }).text, st.size));
  }
}

export function height(blocks: Block[]): number {
  return blocks.reduce((n, b, i) => n + blockHeight(b, i === 0), 0);
}

/**
 * 덩어리 묶음을 예산 안에서 장으로 나눈다. keep 은 머리(첫 장에만)로 함께 있어야 하는 앞 덩어리 수.
 * 한 덩어리가 혼자서도 넘치면 그 덩어리만 한 장에 둔다(쪼개지 않는다) — 그림 찍기가 넘침으로 잡는다.
 */
function pack(blocks: Block[], budget = BODY_BUDGET): Block[][] {
  const pages: Block[][] = [];
  let cur: Block[] = [];
  for (const b of blocks) {
    const next = [...cur, b];
    // 머리 글(h) 이 장 끝에 홀로 남지 않게: h 를 넣을 때 다음 덩어리 몫도 함께 본다.
    if (cur.length && height(next) > budget) {
      // 장 끝의 머리 글은 다음 장으로 옮긴다.
      const carry: Block[] = [];
      while (cur.length && cur[cur.length - 1].t === "h") carry.unshift(cur.pop()!);
      if (cur.length) pages.push(cur);
      cur = [...carry, b];
    } else cur = next;
  }
  if (cur.length) pages.push(cur);
  return pages;
}

// 주장 장의 근거 출처: 기관 이름과 문서 제목만(주소는 마지막 장과 이슈 화면에).
const shortSrc = (s: Source) => ({ t: "src" as const, by: s.by, title: s.title, host: "" });
function uniqSources(list: Source[]): Source[] {
  const seen = new Set<string>();
  return list.filter((s) => {
    const k = `${s.by}|${s.title}|${s.url}`;
    if (seen.has(k) || !(s.by || s.title)) return false;
    seen.add(k);
    return true;
  });
}

function claimBlocks(c: Claim): Block[] {
  const past = c.history.length ? c.history[c.history.length - 1].from : "";
  const out: Block[] = [
    { t: "gist", text: c.gist, kind: c.kind },
    { t: "verdict", verdict: c.verdict, past, evidence: c.evidence_label },
  ];
  // 판정을 받치는 확인된 사실 문장(자료의 basis). 없으면 그리지 않는다.
  if (c.basis.length) {
    out.push({ t: "h", text: "근거가 말하는 것" });
    for (const x of c.basis) out.push({ t: "li", text: x });
  }
  if (c.parts.length) {
    out.push({ t: "h", text: "나눠 본 판정" });
    for (const p of c.parts) {
      out.push({ t: "part", verdict: p.verdict, core: p.core, text: p.gist });
      for (const x of p.basis) out.push({ t: "li", text: x });
    }
  }
  // 이슈 화면(ClaimRow)과 같은 규칙: 까닭과 "무엇이 나오면"은 확인 못 함·일부 맞음에만.
  const showReasons = c.verdict === "확인 못 함" || c.verdict === "일부 맞음";
  if (showReasons && c.reasons.length) {
    out.push({ t: "h", text: "판정하지 못한 까닭" });
    for (const r of c.reasons) out.push({ t: "li", text: r });
  }
  if (showReasons && c.would_decide) {
    out.push({ t: "h", text: "무엇이 나오면 판정할 수 있나" });
    out.push({ t: "p", text: c.would_decide });
  }
  const srcs = uniqSources(c.sources);
  if (srcs.length) {
    out.push({ t: "h", text: "근거 출처" });
    for (const s of srcs) out.push(shortSrc(s));
  }
  return out;
}

export type DeckPaths = { issue: string; fixed: string; site: string };

/** 이슈 하나의 카드 묶음. b 는 최신판 본문(이슈 화면과 같은 것). */
export function buildDeck(site: Site, is: Issue, b: Body, paths: DeckPaths): Deck {
  const revs = revNumbers(is);
  const fixed = b.rev !== null && revs.includes(b.rev) && !is.takenDown.has(b.rev);
  const date = fmtDate(b.rev_at);
  const metaLine = [date, b.rev !== null ? `${b.rev}판` : ""].filter(Boolean).join(" · ");

  // 판정 집계: 이슈 화면 판정표 머리와 같은 값(verdicts.summary). 비면 묶음에서 센다.
  let summary = b.verdicts.summary;
  if (!summaryTotal(summary)) {
    const s = emptySummary();
    for (const g of b.verdicts.groups) for (const c of g.claims) if ((VERDICTS as readonly string[]).includes(c.verdict)) s[c.verdict as keyof Summary]++;
    summary = s;
  }
  const total = summaryTotal(summary);

  const cards: Card[] = [];
  const add = (kind: CardKind, label: string, blocks: Block[], claimVerdict = "") => {
    pack(blocks).forEach((pg, i) => cards.push({ kind, label: i ? `${label} (이어서)` : label, cont: i > 0, blocks: pg, claimVerdict }));
  };

  // 1. 표지
  const cover: Block[] = [{ t: "title", text: b.title, example: b.example }];
  if (metaLine) cover.push({ t: "meta", text: metaLine });
  if (total) cover.push({ t: "h", text: `주장 ${total}건의 판정` }, { t: "summary", summary, total });
  else cover.push({ t: "p", text: "판정할 주장 없이 확인된 사실만 정리했다.", ui: true });
  if (b.verdicts.hidden_claims > 0) cover.push({ t: "p", text: `이 밖에 다루지 않은 주장 ${b.verdicts.hidden_claims}건(공개 기준)`, ui: true, small: true });
  // 표지는 나누지 않는다(제목은 60자 이하라 판정 집계와 한 장에 든다 — 그림 찍기가 넘침을 다시 잰다).
  cards.push({ kind: "cover", label: "OZL 이슈 기록", cont: false, blocks: cover, claimVerdict: "" });

  // 2. 무엇이 새로운가, 왜 중요한가
  const intro: Block[] = [];
  if (b.what_new) intro.push({ t: "h", text: "무엇이 새로운가" }, { t: "p", text: b.what_new });
  if (b.why_matters) intro.push({ t: "h", text: "왜 중요한가" }, { t: "p", text: b.why_matters });
  if (b.masked) intro.push({ t: "p", text: b.masked, small: true });
  if (intro.length) add("intro", "이번 판", intro);

  // 3. 주장마다 한 장(판정표와 같은 순서). 자료에 실린 주장만 — 공개 기준으로 뺀 것은 자료에 없다.
  const claims = sortGroups(b.verdicts.groups).flatMap((g) => g.claims);
  claims.forEach((c, i) => add("claim", `주장 ${i + 1}/${claims.length}`, claimBlocks(c), c.verdict));

  // 4. 남은 질문
  if (b.open_questions.length) add("questions", "아직 모르는 것", b.open_questions.map((q) => ({ t: "li", text: q }) as Block));

  // 5. 출처, 정정 안내, 판과 주소
  // 마지막 장의 출처 목록은 이름과 호스트만(문서 제목은 주장 장과 이슈 화면에 있다).
  const end: Block[] = [{ t: "h", text: "출처" }];
  const seenHost = new Set<string>();
  for (const s of uniqSources(b.sources)) {
    const k = `${s.by}|${host(s.url)}`;
    if (seenHost.has(k)) continue;
    seenHost.add(k);
    end.push({ t: "src", by: s.by || s.title, title: "", host: host(s.url) });
  }
  if (end.length === 1) end.push({ t: "p", text: "이 기록에 실린 출처가 없다.", ui: true, small: true });
  const nCorr = b.corrections.filter((c) => c.kind === "정정").length;
  end.push({ t: "h", text: "정정과 판" });
  end.push({ t: "p", text: nCorr ? `이 판까지 정정 ${nCorr}건. 정정과 판 기록은 이슈 화면에 있다.` : "틀린 곳을 찾으면 알려 달라. 고친 내용은 이슈 화면의 정정 기록에 남긴다.", ui: true, small: true });
  end.push({ t: "link", text: "이슈 화면에서 전부 보기", href: paths.issue, shown: paths.site + paths.issue });
  if (fixed) end.push({ t: "link", text: `${b.rev}판 고정 주소`, href: paths.fixed, shown: paths.site + paths.fixed });
  else end.push({ t: "p", text: "이 판은 아직 고정 주소가 없다.", ui: true, small: true });
  add("end", "출처와 정정", end);

  return { slug: is.slug, title: b.title, rev: b.rev, date, example: b.example, fixed, fixedPath: paths.fixed, issuePath: paths.issue, cards };
}

/** 장 하나에 실린 글(cards.json). from: data 는 자료의 문장 그대로, ui 는 화면이 붙인 머리와 안내. */
export function cardTexts(c: Card): { text: string; from: "data" | "ui" }[] {
  const out: { text: string; from: "data" | "ui" }[] = [];
  for (const b of c.blocks) {
    switch (b.t) {
      case "title": case "gist": case "li": out.push({ text: b.text, from: "data" }); break;
      case "p": out.push({ text: b.text, from: b.ui ? "ui" : "data" }); break;
      case "h": case "meta": out.push({ text: b.text, from: "ui" }); break;
      case "part": out.push({ text: b.text, from: "data" }); break;
      case "verdict": if (b.evidence) out.push({ text: b.evidence, from: "data" }); break;
      case "src": if (b.by) out.push({ text: b.by, from: "data" }); if (b.title) out.push({ text: b.title, from: "data" }); break;
      case "link": out.push({ text: b.text, from: "ui" }); break;
      default: break;
    }
  }
  return out;
}

export function cardVerdicts(c: Card): { verdict: string; text: string; past?: string }[] {
  const out: { verdict: string; text: string; past?: string }[] = [];
  const gist = c.blocks.find((b) => b.t === "gist") as { text: string } | undefined;
  for (const b of c.blocks) {
    if (b.t === "verdict") out.push({ verdict: b.verdict, text: gist?.text ?? "", ...(b.past ? { past: b.past } : {}) });
    if (b.t === "part") out.push({ verdict: b.verdict, text: b.text });
  }
  return out;
}

export function cardSources(c: Card): { by: string; title: string; host: string }[] {
  return c.blocks.filter((b): b is Extract<Block, { t: "src" }> => b.t === "src").map((b) => ({ by: b.by, title: b.title, host: b.host }));
}

/** 사이트 주소 앞부분(그림에 적는 고정 주소). 없으면 경로만 적는다. */
const ORIGIN = (process.env.OZL_SITE_ORIGIN || "").replace(/\/+$/, "");

/** 이슈 화면(최신판)과 같은 본문으로 카드 묶음을 만든다. */
export function deckFor(site: Site, is: Issue): Deck {
  const b = is.latest;
  return buildDeck(site, is, b, { issue: issueUrl(is.slug), fixed: revUrl(is.slug, b.rev ?? 0), site: ORIGIN });
}
