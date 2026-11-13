// 카드 넘기기(설계 4-17). 손가락은 CSS scroll-snap 이 맡고, 여기서는 단추, 좌우 화살표 키, "3 / 8" 표시만 붙인다.
// 넘길 때 움직이는 효과를 쓰지 않는다(바로 그 장으로 간다).
const deck = document.querySelector<HTMLElement>("[data-deck]");
if (deck) {
  const view = deck.querySelector<HTMLElement>("[data-deck-view]")!;
  const items = [...deck.querySelectorAll<HTMLElement>(".deck-item")];
  const count = deck.querySelector<HTMLElement>("[data-deck-count]")!;
  const prev = deck.querySelector<HTMLButtonElement>("[data-deck-prev]")!;
  const next = deck.querySelector<HTMLButtonElement>("[data-deck-next]")!;
  const total = items.length;
  let cur = 0;

  deck.dataset.enhanced = "true";
  view.tabIndex = 0;
  deck.querySelector<HTMLElement>("[data-deck-controls]")!.hidden = false;
  document.querySelector<HTMLElement>("[data-deck-hint]")?.removeAttribute("hidden");
  document.querySelector<HTMLElement>("[data-deck-nohint]")?.setAttribute("hidden", "");

  const indexNow = () => {
    const w = view.clientWidth || 1;
    const gap = items.length > 1 ? items[1].offsetLeft - items[0].offsetLeft - items[0].offsetWidth : 0;
    return Math.max(0, Math.min(total - 1, Math.round(view.scrollLeft / (w + gap))));
  };
  const show = (i: number) => {
    cur = i;
    count.textContent = `${i + 1} / ${total}`;
    prev.setAttribute("aria-disabled", String(i === 0));
    next.setAttribute("aria-disabled", String(i === total - 1));
    items.forEach((it, j) => it.toggleAttribute("data-current", j === i));
  };
  const go = (i: number) => {
    if (i < 0 || i >= total) return;
    view.scrollTo({ left: items[i].offsetLeft - items[0].offsetLeft, behavior: "auto" });
    show(i);
  };

  prev.addEventListener("click", () => go(cur - 1));
  next.addEventListener("click", () => go(cur + 1));
  let t: number | undefined;
  view.addEventListener("scroll", () => {
    clearTimeout(t);
    t = window.setTimeout(() => {
      const i = indexNow();
      if (i !== cur) show(i);
    }, 80);
  }, { passive: true });
  document.addEventListener("keydown", (e) => {
    if (e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    const el = e.target as HTMLElement | null;
    if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
    if (e.key === "ArrowRight") { e.preventDefault(); go(cur + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(cur - 1); }
  });
  window.addEventListener("resize", () => go(cur));
  show(0);
}
