// Test E2E: wgranie pliku → postęp → raport z podświetleniami → historia → telefon.
// Uruchom: serwer na BASE_URL (domyślnie http://127.0.0.1:8765), potem
//   NODE_PATH=$(npm root -g) E2E_TEXT="$(cat tekst.txt)" node tests/e2e/e2e.mjs
import { createRequire } from "node:module";
import { writeFileSync } from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright"); // globalny pakiet: NODE_PATH=$(npm root -g)

const BASE = process.env.BASE_URL || "http://127.0.0.1:8765";
const SHOTS = process.env.SHOTS_DIR || ".";
const FILE = "/tmp/Bardzo_dluga_nazwa_pliku_pracy_licencjackiej_wersja_ostateczna_poprawiona.txt";
writeFileSync(FILE, process.env.E2E_TEXT);

const fail = (msg) => { console.error(msg); process.exit(1); };
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

// Landing pod "/", aplikacja pod "/app".
await page.goto(BASE);
await page.getByRole("heading", { level: 1, name: "Sprawdź pracę, zanim ją oddasz." }).waitFor();
await page.getByRole("link", { name: "Otwórz aplikację" }).first().click();
await page.getByText("Sprawdź pracę przed oddaniem").waitFor();
await page.setInputFiles("#file", FILE);
await page.getByText("Bardzo_dluga_nazwa").waitFor();
await page.getByRole("button", { name: "Sprawdź dokument" }).click();
await page.locator(".kpi").first().waitFor({ timeout: 30000 });
await page.locator("mark.exact").first().waitFor();
const reportUrl = page.url();
await page.screenshot({ path: `${SHOTS}/e2e-report.png` });
await page.locator("mark.exact").first().click();
await page.locator(".detail-pop").waitFor();
if ((await page.locator(".detail-pop").innerText()).includes("null")) fail("Tekst 'null' w szczegółach źródła!");
await page.getByRole("tab", { name: /Źródła/ }).click();
if ((await page.locator("#view").innerText()).includes("null")) fail("Tekst 'null' na liście źródeł!");
await page.getByRole("tab", { name: /Detekcja AI/ }).click();
await page.getByText(/Wynik: \d+%/).waitFor();
await page.screenshot({ path: `${SHOTS}/e2e-ai.png` });
await page.goto(`${BASE}/app#/history`);
await page.getByText("Bardzo_dluga_nazwa").first().waitFor();

// Telefon: strona startowa i raport z długą nazwą pliku — bez poziomego scrolla.
const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, storageState: await ctx.storageState() });
const mobile = await mctx.newPage();
const overflows = () => mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
await mobile.goto(BASE);
await mobile.getByRole("heading", { level: 1, name: "Sprawdź pracę, zanim ją oddasz." }).waitFor();
if (await overflows()) fail("Poziomy scroll na telefonie (landing)!");
await mobile.goto(`${BASE}/app`);
await mobile.getByText("Sprawdź pracę przed oddaniem").waitFor();
if (await overflows()) fail("Poziomy scroll na telefonie (start aplikacji)!");
await mobile.goto(reportUrl);
await mobile.locator(".kpi").first().waitFor();
if (await overflows()) fail("Poziomy scroll na telefonie (raport)!");
await mobile.screenshot({ path: `${SHOTS}/e2e-mobile.png` });
await browser.close();
if (errors.length) fail("Błędy JS: " + errors.join("; "));
console.log("E2E OK");
