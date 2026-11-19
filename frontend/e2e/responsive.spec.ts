import { expect, test, type Page } from "@playwright/test";
import { sessionFor } from "./helpers";

// Runs after journey.spec.ts (files run in name order) and reuses the data it created.
// Every main screen must fit the viewport at phone, tablet and desktop widths: wide tables
// scroll inside their card, the page itself never scrolls sideways.
const VIEWPORTS = [
  { name: "phone", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1280, height: 800 },
];

async function href(page: Page, name: string | RegExp): Promise<string> {
  const value = await page.getByRole("link", { name }).first().getAttribute("href");
  if (!value) throw new Error(`no link ${name}`);
  return value;
}

test("no screen overflows horizontally at phone, tablet or desktop width", async ({ browser }) => {
  test.setTimeout(180_000);
  const page = await sessionFor(browser, "analyst");

  // Collect one URL per screen by navigating the published September period.
  const screens: Record<string, string> = { overview: "/", periods: "/periods", publications: "/publications", audit: "/audit" };
  await page.goto("/periods");
  screens.period = await href(page, "2026-09");
  screens.version = await href(page, "SUPINV-2026-09-v1");
  await page.goto(screens.version);
  screens.findings = await href(page, "Findings");
  screens.impact = await href(page, "Impact");
  screens.review = await href(page, "Review and publish");
  await page.goto(screens.findings);
  screens.finding = await href(page, "INV_FK_SUPPLIER");
  await page.goto("/publications");
  screens.publication = await href(page, /PUB-SUPINV/);

  for (const viewport of VIEWPORTS) {
    await page.setViewportSize(viewport);
    for (const [name, url] of Object.entries(screens)) {
      await page.goto(url);
      await page.waitForLoadState("networkidle");
      await expect(page.locator("main h1").first()).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${name} at ${viewport.name} overflows by ${overflow}px`).toBeLessThanOrEqual(0);
      await page.screenshot({ path: `test-results/screens/${viewport.name}-${name}.png`, fullPage: true });
    }
  }
  await page.context().close();

  // The sign-in screen and the admin's user screen.
  const admin = await sessionFor(browser, "admin");
  for (const viewport of VIEWPORTS) {
    await admin.setViewportSize(viewport);
    await admin.goto("/users");
    await expect(admin.getByRole("heading", { name: "Users", exact: true })).toBeVisible();
    const overflow = await admin.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `users at ${viewport.name}`).toBeLessThanOrEqual(0);
    await admin.screenshot({ path: `test-results/screens/${viewport.name}-users.png`, fullPage: true });
  }
  await admin.context().close();
});
