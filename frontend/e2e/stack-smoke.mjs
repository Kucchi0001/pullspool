/**
 * Browser-level smoke test against the running docker compose stack.
 * Accepts Caddy's internal CA (self-signed) via ignoreHTTPSErrors.
 */
import { chromium } from "playwright-core";

const BASE = process.env.STACK_BASE ?? "https://127.0.0.1:18443";
const PASSWORD = process.env.STACK_PASSWORD ?? "Docker-Test-2026";
const CHROME =
  process.env.CHROME_PATH ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const OUT = process.env.STACK_SHOT ?? "screenshots/stack-overview.png";

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  ignoreHTTPSErrors: true,
});
const page = await context.newPage();
const consoleErrors = [];
const pageErrors = [];
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
page.on("pageerror", (error) => pageErrors.push(String(error)));

await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
await page.waitForSelector("[data-testid=login-submit]");
await page.fill("[data-testid=login-username]", "admin");
await page.fill("[data-testid=login-password]", PASSWORD);
await page.click("[data-testid=login-submit]");
await page.waitForURL((url) => new URL(url).pathname === "/", { timeout: 20000 });
await page.waitForSelector(".page-title");
await page.waitForTimeout(1500);

const summary = await page.evaluate(() => ({
  title: document.title,
  heading: document.querySelector(".page-title")?.textContent?.trim(),
  sse: document.querySelector(".live")?.textContent?.trim(),
  kpis: [...document.querySelectorAll(".kpi .label")].map((node) => node.textContent?.trim()),
  rows: document.querySelectorAll(".mini-row, .ready-row").length,
}));
await page.screenshot({ path: OUT, fullPage: true });
console.log(JSON.stringify({ ...summary, consoleErrors, pageErrors }, null, 2));

await context.close();
await browser.close();
