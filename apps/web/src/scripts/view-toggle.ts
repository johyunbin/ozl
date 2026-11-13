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
  document.querySelectorAll<HTMLDetailsElement>("details[data-claim-open]").forEach((d) => {
    if (d.dataset.claimOpen === "keep") d.open = true;
    else if (v === "short") d.open = false;
  });
}

const group = document.querySelector<HTMLElement>("[data-view-toggle]");
if (group) {
  group.hidden = false;
  apply(read());
  group.addEventListener("click", (e) => {
    const b = (e.target as HTMLElement).closest("button");
    if (!b || !b.dataset.view) return;
    apply(b.dataset.view);
    save(b.dataset.view);
    b.focus();
  });
}
