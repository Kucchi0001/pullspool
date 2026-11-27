/**
 * Capture desktop/mobile screenshots of every page in both themes.
 *
 * Logs in once through the API and reuses the session cookie for every
 * browser context, so the login rate limiter is not triggered by the harness.
 */
import { mkdir } from "node:fs/promises";
import path from "node:path";

import { chromium, request } from "playwright-core";

const BASE = process.env.UI_BASE ?? "http://127.0.0.1:18080";
const OUT = process.env.UI_OUT ?? "screenshots";
const PASSWORD = process.env.UI_PASSWORD ?? "";
if (!PASSWORD) {
  throw new Error("请通过 UI_PASSWORD 提供管理员密码");
}
const CHROME =
  process.env.CHROME_PATH ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

const VIEWPORTS = [
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1024x768", width: 1024, height: 768 },
  { name: "390x844", width: 390, height: 844, mobile: true },
  { name: "375x667", width: 375, height: 667, mobile: true },
  { name: "2560x1440", width: 2560, height: 1440 },
  { name: "3840x2160", width: 3840, height: 2160 },
];

const PAGES = [
  { name: "overview", path: "/" },
  { name: "downloads", path: "/downloads" },
  { name: "ready", path: "/ready" },
  { name: "history", path: "/history" },
  { name: "settings", path: "/settings" },
];

const problems = [];

async function main() {
  const api = await request.newContext({ baseURL: BASE });
  const login = await api.post("/api/auth/login", {
    data: { username: "admin", password: PASSWORD },
  });
  if (!login.ok()) {
    throw new Error(`login failed: HTTP ${login.status()} ${await login.text()}`);
  }
  const storage = await api.storageState();
  await api.dispose();

  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  try {
    // Login page itself, unauthenticated.
    for (const viewport of [VIEWPORTS[1], VIEWPORTS[3]]) {
      const context = await browser.newContext({
        viewport: { width: viewport.width, height: viewport.height },
        deviceScaleFactor: 1,
        isMobile: Boolean(viewport.mobile),
        hasTouch: Boolean(viewport.mobile),
      });
      const page = await context.newPage();
      await page.addInitScript(() => localStorage.setItem("pullspool.theme", "light"));
      await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector("[data-testid=login-submit]");
      await page.waitForTimeout(350);
      const dir = path.join(OUT, "light");
      await mkdir(dir, { recursive: true });
      await page.screenshot({
        path: path.join(dir, `${viewport.name}-login.png`),
        fullPage: true,
      });
      await context.close();
    }

    for (const theme of ["light", "dark"]) {
      for (const viewport of VIEWPORTS) {
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          deviceScaleFactor: 1,
          isMobile: Boolean(viewport.mobile),
          hasTouch: Boolean(viewport.mobile),
          storageState: storage,
        });
        const page = await context.newPage();
        await page.addInitScript((mode) => {
          localStorage.setItem("pullspool.theme", mode);
        }, theme);

        const dir = path.join(OUT, theme);
        await mkdir(dir, { recursive: true });

        for (const target of PAGES) {
          // SSE keeps a connection open forever, so "networkidle" never fires.
          await page.goto(`${BASE}${target.path}`, { waitUntil: "domcontentloaded" });
          await page.waitForSelector(".page-title");
          await page.waitForTimeout(2200);
          const overflow = await page.evaluate(() => ({
            scrollWidth: document.documentElement.scrollWidth,
            innerWidth: window.innerWidth,
          }));
          if (overflow.scrollWidth > overflow.innerWidth + 1) {
            problems.push(
              `${theme} ${viewport.name} ${target.name}: horizontal overflow ${overflow.scrollWidth} > ${overflow.innerWidth}`,
            );
          }
          await page.screenshot({
            path: path.join(dir, `${viewport.name}-${target.name}.png`),
            fullPage: true,
          });
        }
        await context.close();
      }
    }
  } finally {
    await browser.close();
  }

  if (problems.length) {
    console.log("OVERFLOW_PROBLEMS");
    for (const problem of problems) console.log(" -", problem);
    process.exitCode = 1;
  } else {
    console.log("NO_OVERFLOW");
  }
  console.log("screenshots written to", path.resolve(OUT));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
