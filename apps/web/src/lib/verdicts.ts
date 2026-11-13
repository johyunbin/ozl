// 판정 넷의 이름, 순서, 모양.
export const VERDICTS = ["확인", "일부 맞음", "사실과 다름", "확인 못 함"] as const;
export type Verdict = (typeof VERDICTS)[number];

/** 판정 요약 줄의 순서(확인 → 일부 맞음 → 사실과 다름 → 확인 못 함). */
export const SUMMARY_ORDER: readonly Verdict[] = VERDICTS;
/** 판정표 묶음 순서(설계 4-2). */
export const TABLE_ORDER: readonly Verdict[] = ["사실과 다름", "일부 맞음", "확인", "확인 못 함"];

export const VERDICT_CLASS: Record<Verdict, string> = {
  확인: "v-confirmed",
  "일부 맞음": "v-partial",
  "사실과 다름": "v-false",
  "확인 못 함": "v-unknown",
};

export function isVerdict(v: unknown): v is Verdict {
  return typeof v === "string" && (VERDICTS as readonly string[]).includes(v);
}

export type Summary = Record<Verdict, number>;

export function emptySummary(): Summary {
  return { 확인: 0, "일부 맞음": 0, "사실과 다름": 0, "확인 못 함": 0 };
}

export function summaryTotal(s: Summary): number {
  return VERDICTS.reduce((n, v) => n + (s[v] || 0), 0);
}

/** 0건이 아닌 판정만 요약 순서대로. */
export function summaryParts(s: Summary): { verdict: Verdict; n: number }[] {
  return SUMMARY_ORDER.filter((v) => (s[v] || 0) > 0).map((v) => ({ verdict: v, n: s[v] }));
}

/** 글자만의 요약 "확인 1 · 일부 맞음 1"(검색 메타, 화면 읽기용). */
export function summaryText(s: Summary): string {
  const parts = summaryParts(s);
  return parts.length ? parts.map((p) => `${p.verdict} ${p.n}`).join(" · ") : "판정할 주장 없음";
}

/** 묶음을 판정표 순서로 다시 놓는다. 넷 밖의 판정 묶음은 맨 뒤. */
export function sortGroups<T extends { verdict: string }>(groups: T[]): T[] {
  const rank = (v: string) => {
    const i = (TABLE_ORDER as readonly string[]).indexOf(v);
    return i < 0 ? TABLE_ORDER.length : i;
  };
  return [...groups].sort((a, b) => rank(a.verdict) - rank(b.verdict));
}
