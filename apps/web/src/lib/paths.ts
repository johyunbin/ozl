// 안쪽 주소는 모두 여기서 만든다. 기준 경로(BASE_URL)를 붙이고, 손으로 "/" 를 쓰지 않는다.
const RAW_BASE = import.meta.env.BASE_URL || "/";
export const BASE = RAW_BASE.endsWith("/") ? RAW_BASE : `${RAW_BASE}/`;

/** 기준 경로 아래 주소. rel 은 "i/slug/" 처럼 "/" 없이 시작한다. */
export function url(rel = ""): string {
  return BASE + rel.replace(/^\/+/, "");
}

export const issueUrl = (slug: string) => url(`i/${slug}/`);
export const revUrl = (slug: string, rev: number) => url(`i/${slug}/r/${rev}/`);
export const dayUrl = (date: string) => url(`d/${date}/`);
export const monthUrl = (ym: string) => url(`d/${ym}/`);

/** 키워드 주소 규칙(설계 1-1): NFC, 앞뒤 공백 지움, 공백 묶음 → "-", / ? # % \ 와 제어 문자 지움. 한글은 그대로. */
export function keywordSlug(k: string): string {
  return k
    .normalize("NFC")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[\/?#%\\\u0000-\u001f\u007f]/g, "");
}

export const keywordUrl = (k: string) => url(`k/${encodeURI(keywordSlug(k))}/`);
export const keywordSlugUrl = (slug: string) => url(`k/${encodeURI(slug)}/`);
