// 주장의 차례와 쪽 안 주소(설계 4-2). 판정표, 주장 목차, 카드가 같은 차례를 쓴다.
import type { Body, Claim } from "./data";
import { sortGroups } from "./verdicts";

export type Placed = { c: Claim; anchor: string; n: number };

/** 판정표 순서(사실과 다름 → 일부 맞음 → 확인 → 확인 못 함)로 편 주장과 그 쪽 안 주소. */
export function orderedClaims(b: Body): Placed[] {
  const out: Placed[] = [];
  const used = new Set<string>();
  for (const g of sortGroups(b.verdicts.groups.filter((g) => g.claims.length))) {
    for (const c of g.claims) {
      const n = out.length + 1;
      let a = `claim-${(c.id || String(n)).replace(/[^A-Za-z0-9_-]/g, "")}`;
      if (used.has(a)) a = `claim-n${n}`;
      used.add(a);
      out.push({ c, anchor: a, n });
    }
  }
  return out;
}
