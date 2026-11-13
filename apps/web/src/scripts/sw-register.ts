// 서비스 워커 등록(설계 4-18). scope 는 기준 경로(/ 또는 /preview/). 연결되면 내림 목록부터 확인하게 한다.
const base = import.meta.env.BASE_URL.endsWith("/") ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
if ("serviceWorker" in navigator) {
  const ask = () => {
    if (!navigator.onLine) return;
    navigator.serviceWorker.ready.then((r) => r.active?.postMessage({ type: "sync" })).catch(() => {});
  };
  navigator.serviceWorker.register(`${base}sw.js`, { scope: base }).then(ask, () => {});
  window.addEventListener("online", ask);
}
