// Zgodność wstecz: aplikacja była wcześniej pod "/", więc stare linki "/#/job/…"
// i "/#/history" przekierowujemy do "/app" (przy wejściu i przy zmianie kotwicy).
function redirectOldAppLinks() {
  if (location.hash.startsWith("#/")) location.replace("/app" + location.hash);
}
redirectOldAppLinks();
window.addEventListener("hashchange", redirectOldAppLinks);
