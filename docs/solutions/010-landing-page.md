# 010 — Landing page pod "/", aplikacja pod "/app" (v1.3)

**Decyzja.** Strona główna (`app/static/landing.html` + `.css` + `.js`) opisuje narzędzie
studentom korzystającym z instancji; aplikacja przeniesiona pod `/app`. Stare linki
`/#/job/…`, `/#/history` przekierowuje `landing.js` (przy wejściu i przy zmianie kotwicy).

**Zasady treści.** Bez wymyślonych opinii, logotypów i statystyk — tylko fakty z projektu
(formaty, 72 h, 0 zł na Oracle, źródła danych). Zastrzeżenie „nie zastępuje JSA” wysoko na stronie,
osobna sekcja „Czego PlagCheck nie sprawdza”. Kontakt w stopce: acdx@duck.com.

**Technicznie.** Zero inline (CSP `script-src/style-src 'self'`) — pilnuje tego test
`test_landing_has_no_inline_scripts_or_styles`. Prawdziwe zrzuty aplikacji w `app/static/img/`,
w ciemnym motywie podmieniane przez `<picture>` na warianty `-dark`. FAQ na `<details>` (działa
bez JS, z klawiatury). Sprawdzone: 1440/820/390 px × jasny/ciemny, kolejność Tab, skip-link.
