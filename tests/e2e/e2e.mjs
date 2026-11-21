// Test E2E: wgranie pliku → postęp → raport z podświetleniami → historia.
// Uruchom: serwer na BASE_URL (domyślnie http://127.0.0.1:8765), potem `node tests/e2e/e2e.mjs`.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright"); // globalny pakiet: NODE_PATH=$(npm root -g)
import { writeFileSync } from "node:fs";

const BASE = process.env.BASE_URL || "http://127.0.0.1:8765";
const SHOTS = process.env.SHOTS_DIR || ".";
const text = process.env.E2E_TEXT;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

await page.goto(BASE);
await page.getByText("Sprawdź pracę przed oddaniem").waitFor();
writeFileSync("/tmp/e2e-praca.txt", text);
await page.setInputFiles("#file", "/tmp/e2e-praca.txt");
await page.getByText("e2e-praca.txt").waitFor();
await page.getByRole("button", { name: "Sprawdź dokument" }).click();
await page.locator(".kpi").first().waitFor({ timeout: 30000 });
await page.locator("mark.exact").first().waitFor();
await page.screenshot({ path: `${SHOTS}/e2e-report.png`, fullPage: false });
await page.locator("mark.exact").first().click();
await page.locator(".detail-pop").waitFor();
await page.getByRole("tab", { name: /Detekcja AI/ }).click();
await page.getByText(/Wynik: \d+%/).waitFor();
await page.screenshot({ path: `${SHOTS}/e2e-ai.png` });
await page.goto(`${BASE}/#/history`);
await page.getByText("e2e-praca.txt").waitFor();
const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
await mobile.goto(BASE);
await mobile.getByText("Sprawdź pracę przed oddaniem").waitFor();
const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
await mobile.screenshot({ path: `${SHOTS}/e2e-mobile.png` });
await browser.close();
if (overflow) { console.error("Poziomy scroll na mobile!"); process.exit(1); }
if (errors.length) { console.error("Błędy JS:", errors); process.exit(1); }
console.log("E2E OK");
