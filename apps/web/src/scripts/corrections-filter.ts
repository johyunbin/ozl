// 정정 목록 걸러 보기(설계 1-9). 스크립트가 없으면 링크가 쪽 안 자리로 내려간다.
const list = document.querySelector<HTMLElement>("[data-corrections]");
const nav = document.querySelector<HTMLElement>("[data-corrections-filter]");
if (list && nav) {
  nav.addEventListener("click", (e) => {
    const a = (e.target as HTMLElement).closest<HTMLAnchorElement>("a[data-kind]");
    if (!a) return;
    e.preventDefault();
    const kind = a.dataset.kind || "";
    list.querySelectorAll<HTMLElement>("li[data-kind]").forEach((li) => {
      li.hidden = kind !== "all" && li.dataset.kind !== kind;
    });
    nav.querySelectorAll("a[data-kind]").forEach((x) => x.removeAttribute("aria-current"));
    a.setAttribute("aria-current", "true");
  });
}
