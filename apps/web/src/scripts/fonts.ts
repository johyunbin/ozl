// 글꼴 묶음 목록을 그리기를 막지 않게 늦게 붙인다(설계 6). 인라인 이벤트 속성(onload=) 대신 이 파일이 한다.
const href = document.querySelector<HTMLLinkElement>("link[data-font-css]")?.href;
if (href && !document.querySelector(`link[rel="stylesheet"][href="${href}"]`)) {
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = href;
  document.head.append(l);
}
