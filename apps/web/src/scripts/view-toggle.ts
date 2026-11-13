// "짧게 / 전부" 전환(설계 4-12). 고른 값은 localStorage 에 남기고, 못 쓰면 매번 "전부".
const KEY = "ozl-view";
const root = document.documentElement;

function read(): string {
  try {
    return localStorage.getItem(KEY) === "short" ? "short" : "full";
  } catch {
    return "full";
  }
}
function save(v: string) {
  try {
    localStorage.setItem(KEY, v);
  } catch {}
}

function apply(v: string) {
  root.dataset.view = v;
  document.querySelectorAll<HTMLButtonElement>("[data-view-toggle] button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
  // "전부" 는 모든 주장의 근거를 펼치고, "짧게" 는 '사실과 다름' 밖의 것을 접는다(단추 상태와 화면이 맞게).
  document.querySelectorAll<HTMLDetailsElement>("details[data-claim-open]").forEach((d) => {
    d.open = v === "full" || d.dataset.claimOpen === "keep";
  });
}

const group = document.querySelector<HTMLElement>("[data-view-toggle]");
if (group) {
  group.hidden = false;
  // 카드 화면의 "짧게 / 전부" 링크는 ?view= 로 고른 값을 넘긴다. 받으면 남기고 주소에서 지운다.
  try {
    const u = new URL(location.href);
    const v = u.searchParams.get("view");
    if (v === "short" || v === "full") {
      save(v);
      u.searchParams.delete("view");
      history.replaceState(history.state, "", u.pathname + (u.search || "") + u.hash);
    }
  } catch {}
  apply(read());
  group.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest("button");
    if (!b || !b.dataset.view) return;
    apply(b.dataset.view);
    save(b.dataset.view);
    b.focus();
  });
}
