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

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string);
}
/** 발췌는 <mark> 만 남기고 나머지 꺾쇠를 막는다. */
function excerpt(s: string) {
  return esc(s).replace(/&lt;mark&gt;/g, "<mark>").replace(/&lt;\/mark&gt;/g, "</mark>");
}

async function run(q: string) {
  if (!out || !status) return;
  out.innerHTML = "";
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
    status.innerHTML = `'${esc(query)}'에 맞는 기록이 없다. <a href="${esc(base)}k/">키워드 모음</a>에서 찾아볼 수 있다.`;
    return;
  }
  status.textContent = used === query ? `${items.length}건` : `'${used}'(으)로 찾은 결과 ${items.length}건`;
  out.innerHTML = items
    .map((d) => {
      const m = d.meta || {};
      const ex = m.example ? `<span class="tag">예시</span>` : "";
      const cat = m.category ? `<p class="xs muted">${esc(m.category)}</p>` : "";
      return `<li>${cat}<p class="row-title">${ex}<a href="${esc(d.url)}">${esc(m.title || d.url)}</a></p>` +
        `<p class="row-sub">${esc(m.rev || "")}${m.summary ? ` · ${esc(m.summary)}` : ""}</p>` +
        `<p class="small excerpt">${excerpt(d.excerpt || "")}</p></li>`;
    })
    .join("");
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
