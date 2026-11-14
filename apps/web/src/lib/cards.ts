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
import { fmtDate, host, sentences } from "./format";
import { issueUrl, revUrl } from "./paths";
import { emptySummary, sortGroups, summaryTotal, VERDICTS, type Summary } from "./verdicts";

/**
 * 글 덩어리가 한 장에 다 들지 않아 장을 넘겨 이을 때의 표시. chain 은 원래 덩어리 하나를 가리키는 이름이고,
 * 같은 chain 의 조각을 차례로 이으면 자료의 문장과 글자 하나 다르지 않다(띄어쓰기까지). cont 는 둘째 조각부터 참.
 */
export type Piece = { chain?: string; cont?: boolean };

export type Block =
  /** size: 제목 글자 크기(--b 배). 제목이 길어 표지가 넘치면 한 단계씩 줄인다(TITLE_SIZES). */
  | { t: "title"; text: string; example: boolean; size: number }
  | { t: "meta"; text: string }
  | { t: "summary"; summary: Summary; total: number }
  | { t: "h"; text: string }
  | ({ t: "p"; text: string; ui?: boolean; small?: boolean } & Piece)
  | { t: "gist"; text: string; kind: string }
  /** evidence: 판정에 쓴 공식 근거의 종류, press: 주장을 실은 보도의 요약(판정 근거가 아니다). */
  | { t: "verdict"; verdict: string; past: string; evidence: string; press: string }
  | { t: "part"; verdict: string; core: boolean; text: string }
  /** 판정이 어디까지를 확인한 것인지(자료의 scope). 머리 "확인한 범위"는 화면이 붙인다. inPart 면 작은 주장 밑. */
  | ({ t: "scope"; text: string; inPart: boolean } & Piece)
  | ({ t: "li"; text: string } & Piece)
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
/**
 * 머리 줄, 꼬리 줄, 안쪽 여백을 뺀 본문 높이(em). 실제 남는 자리는 21.7em(1080 폭에서 1041px)이고,
 * 어림이 실제보다 조금 작게 나오는 장이 있어(실측 7px) 0.7em(34px)을 남긴다.
 */
export const BODY_BUDGET = 21;

/** 표지 제목 글자 크기의 단계(--b 배). 표지가 본문 높이를 넘으면 다음 단계로 줄인다. Card.astro 의 .c-title 과 맞춘다. */
export const TITLE_SIZES = [1.625, 1.375, 1.25, 1.125] as const;

/** 판정 밑 범위 줄의 머리(화면이 붙인 글). */
export const SCOPE_HEAD = "확인한 범위";
/** 범위 문장이 앞 장에서 넘어와 이어지는 장의 머리(화면이 붙인 글). */
export const SCOPE_HEAD_CONT = "확인한 범위(이어서)";
export const scopeHead = (b: { cont?: boolean }) => (b.cont ? SCOPE_HEAD_CONT : SCOPE_HEAD);
/** 판정 밑 보도 줄의 머리(화면이 붙인 글). 보도는 판정의 근거로 세지 않으므로 "근거" 줄과 따로 둔다. */
export const PRESS_HEAD = "퍼진 곳";
/** 공식 근거 없이 보도만 있는 주장의 근거 줄(화면이 붙인 글). */
export const NO_OFFICIAL = "판정에 쓴 공식 근거 없음";

/** '확인 못 함' 주장에 붙은 공식 문서의 머리. 그 문서는 판정을 받친 근거가 아니라 어디까지 확인했는지를 보이는 문서다. */
export const DOCS_HEAD = "근거 문서";
export const DOCS_HEAD_UNVERIFIED = "살펴본 공식 문서";
export const docsHead = (verdict: string) => (verdict === "확인 못 함" ? DOCS_HEAD_UNVERIFIED : DOCS_HEAD);
/** 주장에 이어 둔 확인된 사실의 머리말. '확인 못 함'에서는 그 사실이 판정을 받치는 근거가 아니라
 * 주장과 관련해 확인된 것일 뿐이므로 근거라고 부르지 않는다. */
export const BASIS_HEAD = "근거가 말하는 것";
export const BASIS_HEAD_UNVERIFIED = "관련해서 확인된 것";
export const basisHead = (verdict: string) => (verdict === "확인 못 함" ? BASIS_HEAD_UNVERIFIED : BASIS_HEAD);

/** 판정 밑 근거 줄의 글. 공식 근거가 없고 보도만 있으면 NO_OFFICIAL, 둘 다 없으면 빈 글(줄을 그리지 않는다).
 *  '확인 못 함'이면 근거 줄을 그리지 않는다. 판정하지 못한 까닭은 사유 줄이 말하고, "공식 근거 없음"을 덧붙이면
 *  아래의 살펴본 공식 문서와 어긋나 읽힌다. */
export function evidenceLine(evidence: string, press: string, verdict = ""): string {
  if (evidence) return `근거: ${evidence}`;
  if (verdict === "확인 못 함") return "";
  return press ? NO_OFFICIAL : "";
}

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
  scope: { size: 0.9375, lh: 1.5, gap: 0.375 },
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
    case "title": return gap + linesOf(textWidth(b.text) + (b.example ? 1.6 * TITLE_SIZES[0] / b.size : 0), b.size) * b.size * st.lh;
    case "summary": return gap + 4 * 1.6 + 0.5 * 3;
    case "verdict": {
      // 판정 표시(지난 판정 포함) 한 줄 + 근거 줄 + 퍼진 곳 줄.
      const head = 1.6; // 테두리 있는 표시는 조금 더 높다
      const ev = evidenceLine(b.evidence, b.press, b.verdict);
      return gap + head + (ev ? h(lines(ev, st.size)) : 0) + (b.press ? h(lines(`${PRESS_HEAD}: ${b.press}`, st.size)) : 0);
    }
    // 판정 표시(모양 1.3em + 글자)와 "핵심" 꼬리표가 같은 줄 앞에 붙는다.
    case "part": return gap + h(linesOf(textWidth(b.verdict) + 1.3 + (b.core ? 2.4 : 0) + textWidth(b.text), st.size));
    // "확인한 범위: " 머리가 문장 앞 같은 줄에 붙는다. 작은 주장 밑이면 1em 들여 쓴다.
    case "scope": return gap + h(linesOf(textWidth(`${scopeHead(b)}: `) + textWidth(b.text), st.size, b.inPart ? 1 : 0));
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

/** 장을 넘겨 이을 수 있는 덩어리: 자료에서 온 긴 글(범위, 목록 문장, 본문 문단). 화면이 붙인 안내 문장은 짧아 잇지 않는다. */
type Splittable = Extract<Block, { t: "p" | "li" | "scope" }>;
function splittable(b: Block): b is Splittable {
  return b.t === "li" || b.t === "scope" || (b.t === "p" && !b.ui);
}

/**
 * 글을 자를 수 있는 자리(조각이 시작하는 글자 위치). 글자는 바꾸지 않으므로 text.slice(앞 자리, 뒷 자리)를
 * 차례로 이으면 원래 글과 같다. 띄어쓰기는 앞 조각 끝에 남는다.
 * level 0: 문장 사이(format.ts 의 sentences — 따옴표, 괄호 안에서는 가르지 않는다), 1: 낱말 사이, 2: 글자 사이.
 */
function cutPoints(text: string, level: 0 | 1 | 2): number[] {
  const out: number[] = [];
  if (level === 0) {
    let at = 0;
    sentences(text).forEach((one, i) => {
      const k = text.indexOf(one, at);
      if (k < 0) return;
      if (i > 0 && k > 0) out.push(k);
      at = k + one.length;
    });
  } else if (level === 1) {
    for (let i = 1; i < text.length; i++) if (/\s/.test(text[i - 1]) && !/\s/.test(text[i])) out.push(i);
  } else {
    // 글자 사이(드문 경우: 띄어쓰기 없이 한 장보다 긴 낱말). 대리 쌍은 가르지 않는다.
    let i = 0;
    for (const ch of text) { i += ch.length; if (i < text.length) out.push(i); }
  }
  return out;
}

const withText = (b: Splittable, text: string, cont: boolean, chain: string): Splittable => ({ ...b, text, cont, chain });

/**
 * 덩어리 b 의 앞부분을 지금 장(cur)에 남은 자리에 담을 만큼 자른다. 문장 사이에서 먼저 자르고,
 * fine 이면(장이 비어 있거나 머리 글뿐이라 다음 장으로 넘겨도 나아지지 않을 때) 낱말 사이, 글자 사이까지 내려간다.
 * 앞 조각과 남은 조각을 돌려준다. 한 조각도 담지 못하면 null.
 */
function splitToFit(b: Splittable, cur: Block[], budget: number, chain: string, fine: boolean): [Splittable, Splittable] | null {
  const levels: (0 | 1 | 2)[] = fine ? [0, 1, 2] : [0];
  for (const level of levels) {
    const cuts = cutPoints(b.text, level);
    let best = -1;
    // 앞에서부터 늘려 가며 담기는 가장 긴 앞부분을 찾는다(높이는 글 길이에 따라 늘기만 한다).
    for (let i = 0; i < cuts.length; i++) {
      const head = withText(b, b.text.slice(0, cuts[i]), !!b.cont, chain);
      if (height([...cur, head]) <= budget) best = i;
      else break;
    }
    if (best >= 0) {
      const k = cuts[best];
      return [withText(b, b.text.slice(0, k), !!b.cont, chain), withText(b, b.text.slice(k), true, chain)];
    }
  }
  return null;
}

/**
 * 덩어리 묶음을 예산 안에서 장으로 나눈다. key 는 이 묶음의 이름(장을 넘겨 이은 조각의 chain 앞부분).
 * - 덩어리가 지금 장에 다 들지 않으면 다음 장으로 넘긴다. 장 끝에 머리 글(h)이나, 범위가 넘어가는 작은 주장이
 *   남으면 함께 넘긴다(leads).
 * - 자료의 긴 글(한 장의 절반을 넘는 범위, 목록 문장, 문단)은 통째로 넘기지 않고 문장 사이에서 갈라
 *   지금 장의 남은 자리부터 채운다(범위가 판정과 떨어지지 않게). 문장 하나가 한 장보다 길면 낱말 사이에서 가른다.
 * - 글자는 줄이거나 바꾸지 않는다. 쪼갤 수 없는 덩어리가 혼자서 넘치면 그대로 한 장에 두고, 그림 찍기가 넘침으로 잡는다.
 */
function pack(blocks: Block[], key: string, budget = BODY_BUDGET): Block[][] {
  const pages: Block[][] = [];
  let cur: Block[] = [];
  const items = blocks.map((b, i) => ({ b, chain: `${key}#${i}` }));
  while (items.length) {
    const { b, chain } = items.shift()!;
    if (height([...cur, b]) <= budget) { cur.push(b); continue; }
    // 장 끝에서 b 와 함께 다음 장으로 가야 하는 덩어리(머리 글, 작은 주장의 범위 앞 그 작은 주장).
    const carry = leads(cur, b);
    const alone = carry.length === cur.length; // 이 장에는 b 의 머리뿐이다
    if (splittable(b) && blockHeight(b, true) > budget / 2) {
      const sp = splitToFit(b, cur, budget, chain, alone);
      if (sp) {
        cur.push(sp[0]);
        pages.push(cur);
        cur = [];
        items.unshift({ b: sp[1], chain });
        continue;
      }
    }
    if (!alone) {
      pages.push(cur.slice(0, cur.length - carry.length));
      cur = carry;
      items.unshift({ b, chain });
      continue;
    }
    // 빈 장(또는 머리뿐)에도 들지 않는 쪼갤 수 없는 덩어리: 혼자 둔다.
    cur.push(b);
    pages.push(cur);
    cur = [];
  }
  if (cur.length) pages.push(cur);
  return pages;
}

/** 장 끝에 홀로 남기지 않고 다음 덩어리 b 와 함께 넘길 덩어리들: 머리 글(h), 그리고 b 가 작은 주장의 범위면 그 작은 주장. */
function leads(cur: Block[], b: Block): Block[] {
  const out: Block[] = [];
  let next = b;
  for (let i = cur.length - 1; i >= 0; i--) {
    const x = cur[i];
    const lead = x.t === "h" || (x.t === "part" && next.t === "scope" && next.inPart && !next.cont);
    if (!lead) break;
    out.unshift(x);
    next = x;
  }
  return out;
}

// 주장 장의 근거 문서와 참고한 보도: 기관(매체) 이름과 문서 제목만(주소는 마지막 장과 이슈 화면에).
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
    { t: "verdict", verdict: c.verdict, past, evidence: c.evidence_label, press: c.press_label },
  ];
  // 확인한 범위는 판정과 떨어지면 판정을 넓게 읽게 되므로 판정 바로 밑에 둔다.
  if (c.scope) out.push({ t: "scope", text: c.scope, inPart: false });
  // 판정을 받치는 확인된 사실 문장(자료의 basis). 없으면 그리지 않는다.
  if (c.basis.length) {
    out.push({ t: "h", text: basisHead(c.verdict) });
    for (const x of c.basis) out.push({ t: "li", text: x });
  }
  if (c.parts.length) {
    out.push({ t: "h", text: "나눠 본 판정" });
    for (const p of c.parts) {
      out.push({ t: "part", verdict: p.verdict, core: p.core, text: p.gist });
      if (p.scope) out.push({ t: "scope", text: p.scope, inPart: true });
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
  // 판정에 쓴 문서와 참고한 보도를 가른다(이슈 화면의 ClaimRow 와 같은 규칙). 보도는 판정의 근거로 세지 않는다.
  const srcs = uniqSources(c.sources);
  const docs = srcs.filter((s) => s.kind === "공식 원문" || s.kind === "기관 자료");
  const press = srcs.filter((s) => !(s.kind === "공식 원문" || s.kind === "기관 자료"));
  if (docs.length) {
    out.push({ t: "h", text: docsHead(c.verdict) });
    for (const s of docs) out.push(shortSrc(s));
  }
  if (press.length) {
    out.push({ t: "h", text: "참고한 보도" });
    for (const s of press) out.push(shortSrc(s));
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
    pack(blocks, label).forEach((pg, i) => cards.push({ kind, label: i ? `${label} (이어서)` : label, cont: i > 0, blocks: pg, claimVerdict }));
  };

  // 1. 표지
  const coverAt = (size: number): Block[] => {
    const cover: Block[] = [{ t: "title", text: b.title, example: b.example, size }];
    if (metaLine) cover.push({ t: "meta", text: metaLine });
    if (total) cover.push({ t: "h", text: `주장 ${total}건의 판정` }, { t: "summary", summary, total });
    else cover.push({ t: "p", text: "판정할 주장 없이 확인된 사실만 정리했다.", ui: true });
    if (b.verdicts.hidden_claims > 0) cover.push({ t: "p", text: `이 밖에 다루지 않은 주장 ${b.verdicts.hidden_claims}건(공개 기준)`, ui: true, small: true });
    return cover;
  };
  // 표지는 나누지 않는다. 제목이 길어 넘치면 제목 글자만 한 단계씩 줄인다(60자 제목은 1.25 에서 네 줄로 든다).
  // 가장 작은 단계에서도 넘치면 그대로 두고 그림 찍기가 넘침으로 잡는다.
  let cover = coverAt(TITLE_SIZES[0]);
  for (const size of TITLE_SIZES) {
    cover = coverAt(size);
    if (height(cover) <= BODY_BUDGET) break;
  }
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

export type CardText = { text: string; from: "data" | "ui"; chain?: string };
/** 장을 넘겨 이은 조각이면 chain 을 붙인다(그림 찍기가 같은 chain 을 차례로 이어 사본의 문장과 대조한다). */
const piece = (b: Splittable): CardText => (b.chain ? { text: b.text, from: "data", chain: b.chain } : { text: b.text, from: "data" });

/**
 * 장 하나에 실린 글(cards.json). from: data 는 자료의 문장 그대로, ui 는 화면이 붙인 머리와 안내.
 * chain 이 있는 글은 장을 넘겨 이은 조각이고, 같은 chain 을 장 차례로 이으면 자료의 문장 하나가 된다.
 */
export function cardTexts(c: Card): CardText[] {
  const out: CardText[] = [];
  for (const b of c.blocks) {
    switch (b.t) {
      case "title": case "gist": out.push({ text: b.text, from: "data" }); break;
      case "li": out.push(piece(b)); break;
      case "p": out.push(b.ui ? { text: b.text, from: "ui" } : piece(b)); break;
      case "h": case "meta": out.push({ text: b.text, from: "ui" }); break;
      case "part": out.push({ text: b.text, from: "data" }); break;
      case "scope": out.push({ text: scopeHead(b), from: "ui" }, piece(b)); break;
      case "verdict":
        if (b.evidence) out.push({ text: b.evidence, from: "data" });
        else if (evidenceLine(b.evidence, b.press, b.verdict)) out.push({ text: NO_OFFICIAL, from: "ui" });
        if (b.press) out.push({ text: PRESS_HEAD, from: "ui" }, { text: b.press, from: "data" });
        break;
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
