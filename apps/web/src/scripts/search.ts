// 검색(설계 4-15, 5-2). Pagefind API 로 결과를 이 사이트의 목록 모양으로 그린다.
import { retryQueries, words, stem } from "../lib/search-terms";

type Result = { url: string; excerpt: string; meta: Record<string, string> };
type PF = {
  options: (o: Record<string, unknown>) => Promise<void>;
  search: (q: string) => Promise<{ results: { id: string; score: number; data: () => Promise<Result> }[] }>;
};

const form = document.querySelector<HTMLFormElement>("form.search-box");
const out = document.querySelector<HTMLElement>("[data-search-results]");
const status = document.querySelector<HTMLElement>("[data-search-status]");
const nojs = document.querySelector<HTMLElement>("[data-search-nojs]");
const base = form?.dataset.base || "/";
let pf: PF | null = null;

async function load(): Promise<PF> {
  if (pf) return pf;
  const mod = (await import(/* @vite-ignore */ `${base}pagefind/pagefind.js`)) as PF;
  await mod.options({ baseUrl: base });
  pf = mod;
  return mod;
}

/**
 * 검색 도구가 준 발췌를 DOM 으로 옮긴다. <mark>…</mark> 만 표시로 남기고 나머지는 모두 글자(text node)로 둔다.
 * 문자열을 HTML 로 해석하지 않으므로 발췌 안의 어떤 꺾쇠도 요소가 되지 않는다. 발췌의 &amp; 같은 글자 참조는 글자로 푼다.
 */
function excerptNodes(s: string): Node[] {
  const out: Node[] = [];
  const ENT: Record<string, string> = { amp: "&", lt: "<", gt: ">", quot: '"', "#39": "'", "#x27": "'" };
  let inMark = false;
  for (const p of s.split(/(<mark>|<\/mark>)/)) {
    if (p === "<mark>") { inMark = true; continue; }
    if (p === "</mark>") { inMark = false; continue; }
    if (!p) continue;
    const t = document.createTextNode(p.replace(/<[^>]*>/g, "").replace(/&(amp|lt|gt|quot|#39|#x27);/g, (_, e: string) => ENT[e]));
    if (inMark) { const m = document.createElement("mark"); m.append(t); out.push(m); } else out.push(t);
  }
  return out;
}

/** 결과 주소는 이 사이트의 기준 경로 안일 때만 링크로 쓴다. 아니면 undefined(글자로만 그린다). */
function sameSitePath(u: string, base: string): string | undefined {
  try {
    const x = new URL(u, location.origin);
    if (x.origin !== location.origin || !x.pathname.startsWith(base)) return undefined;
    return x.pathname + x.search + x.hash;
  } catch {
    return undefined;
  }
}

function el<K extends keyof HTMLElementTagNameMap>(tag: K, cls = "", text = ""): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text) e.textContent = text;
  return e;
}

async function run(q: string) {
  if (!out || !status) return;
  out.replaceChildren();
  const query = q.trim();
  if (!query) {
    status.textContent = "";
    return;
  }
  status.textContent = "찾는 중";
  let api: PF;
  try {
    api = await load();
  } catch {
    status.textContent = "검색 색인을 불러오지 못했다. 키워드 모음에서 찾을 수 있다.";
    return;
  }
  let used = query;
  let res = await api.search(query);
  if (!res.results.length) {
    for (const alt of retryQueries(query)) {
      const r = await api.search(alt);
      if (r.results.length) {
        res = r;
        used = alt;
        break;
      }
    }
  }
  if (!res.results.length) {
    // 낱말 하나씩(조사를 뗀 꼴) 찾아 합친다.
    const ws = [...new Set(words(query).map(stem))].filter((w) => [...w].length >= 2);
    const seen = new Map<string, { id: string; score: number; data: () => Promise<Result> }>();
    for (const w of ws) {
      const r = await api.search(w);
      for (const x of r.results) {
        const prev = seen.get(x.id);
        seen.set(x.id, prev ? { ...x, score: prev.score + x.score } : x);
      }
    }
    if (seen.size) {
      res = { results: [...seen.values()].sort((a, b) => b.score - a.score) };
      used = ws.join(", ");
    }
  }
  const items = await Promise.all(res.results.slice(0, 20).map((r) => r.data()));
  if (!items.length) {
    status.replaceChildren(`'${query}'에 맞는 기록이 없다. `);
    const a = el("a", "", "키워드 모음");
    a.href = `${base}k/`;
    status.append(a, "에서 찾아볼 수 있다.");
    return;
  }
  status.textContent = used === query ? `${items.length}건` : `'${used}'(으)로 찾은 결과 ${items.length}건`;
  out.replaceChildren(...items.map((d) => {
    const m = d.meta || {};
    const li = el("li");
    if (m.category) li.append(el("p", "xs muted", m.category));
    const t = el("p", "row-title");
    if (m.example) t.append(el("span", "tag", "예시"));
    const href = sameSitePath(d.url, base);
    if (href) {
      const a = el("a", "", m.title || d.url);
      a.href = href;
      t.append(a);
    } else t.append(m.title || d.url);
    li.append(t);
    li.append(el("p", "row-sub", `${m.rev || ""}${m.summary ? ` · ${m.summary}` : ""}`));
    const ex = el("p", "small excerpt");
    ex.append(...excerptNodes(d.excerpt || ""));
    li.append(ex);
    return li;
  }));
}

if (form) {
  if (nojs) nojs.hidden = true;
  const input = form.querySelector<HTMLInputElement>("input[name=q]");
  const q = new URLSearchParams(location.search).get("q") || "";
  if (input) input.value = q;
  if (q) run(q);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const v = input?.value || "";
    const u = new URL(location.href);
    u.searchParams.set("q", v);
    history.replaceState(null, "", u);
    run(v);
  });
}
