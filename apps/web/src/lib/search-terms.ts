// 조사 떼기(설계 5-2). 색인의 숨은 칸과 검색 쪽이 함께 쓴다.
export const PARTICLES = [
  "에서는", "으로는", "에게서", "에서", "으로", "에게", "까지", "부터", "처럼", "보다", "이나", "이다",
  "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만",
].sort((a, b) => b.length - a.length);

const NUM_UNIT = /^\d[\d,.]*[^\d\s]*$/;

/** 끝의 조사를 한 번 뗀다. 남은 말이 2글자 미만이면 원래 말. 숫자+단위는 그대로. */
export function stem(word: string): string {
  const w = word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "");
  if (NUM_UNIT.test(w)) return w;
  for (const p of PARTICLES) {
    if (w.endsWith(p) && [...w].length - [...p].length >= 2) return w.slice(0, w.length - p.length);
  }
  return w;
}

export function words(text: string): string[] {
  return text.split(/\s+/).map((w) => w.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, "")).filter(Boolean);
}

/** 제목과 문장에서 어근 목록(2글자 이상). */
export function roots(texts: string[]): string[] {
  const out = new Set<string>();
  for (const t of texts) {
    for (const w of words(t)) {
      const s = stem(w);
      if ([...s].length >= 2 || NUM_UNIT.test(s)) out.add(s);
    }
  }
  return [...out];
}

/** 찾는 말을 다시 찾을 꼴로: 낱말마다 조사를 떼고, 띄어쓰기를 뺀 꼴을 더한다. */
export function retryQueries(q: string): string[] {
  const ws = words(q);
  const stemmed = ws.map(stem).join(" ");
  const out = new Set<string>();
  if (stemmed && stemmed !== q.trim()) out.add(stemmed);
  const joined = ws.map(stem).join("");
  if (ws.length > 1 && joined) out.add(joined);
  return [...out];
}
