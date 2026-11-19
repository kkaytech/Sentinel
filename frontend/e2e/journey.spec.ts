import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { DATA, REPO, catalogue, sessionFor, signIn, upload } from "./helpers";

// The complete Sentinel journey against the real API and database (PRD §6.1).
// Steps run in order and share the analyst's and the approver's sessions.
test.describe.configure({ mode: "serial" });

const CLEAN = "2026-09"; // "corrected" reference data: one waivable blocker, plus warnings
const DIRTY = "2026-10"; // "defective" reference data: includes non-waivable blockers

let analyst: Page;
let approver: Page;
let versionUrl = "";
let reviewUrl = "";

test.beforeAll(async ({ browser }) => {
  analyst = await sessionFor(browser, "analyst");
  approver = await sessionFor(browser, "approver");
});

test.afterAll(async () => {
  await analyst.context().close();
  await approver.context().close();
});

test("sign-in rejects a wrong password and accepts the right one", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Username").fill("analyst");
  await page.getByLabel("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toContainText("UNAUTHENTICATED");
  await signIn(page, "analyst");
  await expect(page.getByRole("heading", { level: 1, name: /Good (morning|afternoon|evening), Demo Analyst/ })).toBeVisible();
  // The test database starts empty, so the overview shows its empty state.
  await expect(page.getByText("No reporting periods yet").first()).toBeVisible();
});

test("roles see different actions", async ({ browser }) => {
  // The analyst can upload; the approver cannot. Neither can administer users.
  await analyst.goto("/periods");
  await expect(analyst.getByRole("heading", { name: "Upload data" })).toBeVisible();
  await approver.goto("/periods");
  await expect(approver.getByRole("heading", { name: "Periods", exact: true })).toBeVisible();
  await expect(approver.getByRole("heading", { name: "Upload data" })).toHaveCount(0);
  await expect(analyst.getByRole("link", { name: "Users" })).toHaveCount(0);

  const admin = await sessionFor(browser, "admin");
  await admin.getByRole("link", { name: "Users" }).click();
  await expect(admin.getByText("analyst", { exact: true })).toBeVisible();
  await admin.context().close();
});

test("an upload with a missing file is rejected with a clear error", async () => {
  await analyst.goto("/periods");
  await analyst.getByLabel("Reporting period").fill(CLEAN);
  await analyst.getByRole("button", { name: "Upload" }).click();
  await expect(analyst.getByRole("alert")).toContainText("MISSING_TABLE_FILE");
});

test("defective data: validation finds the planted defects and cannot be published", async () => {
  const expected = catalogue(DIRTY).expected_findings;
  await upload(analyst, DIRTY);
  await expect(analyst.getByText("Ingested, not validated")).toBeVisible();
  await analyst.getByRole("button", { name: "Run validation" }).click();
  await expect(analyst).toHaveURL(/\/runs\/[0-9a-f-]+$/);

  // Every rule the generator planted a defect for is reported, with the planted record count.
  for (const [rule, finding] of Object.entries(expected)) {
    const row = analyst.getByRole("row").filter({ has: analyst.getByRole("link", { name: rule, exact: true }) });
    await expect(row).toHaveCount(1);
    await expect(row.getByRole("cell").nth(3)).toHaveText(finding.rows.length.toLocaleString("en-US"));
  }

  // Drill into a duplicate finding: records, groups and a confirmed discrepancy.
  await analyst.getByRole("link", { name: "INV_BK_UNIQUE", exact: true }).click();
  await expect(analyst.getByText("Confirmed discrepancy").first()).toBeVisible();
  await expect(analyst.getByText("canonical", { exact: true }).first()).toBeVisible();
  await expect(analyst.getByText("duplicate", { exact: true }).first()).toBeVisible();

  // A non-waivable rule offers no waiver.
  await analyst.goBack();
  await analyst.getByRole("link", { name: "INV_PK_UNIQUE", exact: true }).click();
  await expect(analyst.getByText("This rule cannot be waived.")).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Request waiver" })).toHaveCount(0);

  // Reporting impact and the gate.
  await analyst.goBack();
  await analyst.getByRole("link", { name: "Reporting impact" }).click();
  await expect(analyst.getByRole("heading", { name: "Version totals" })).toBeVisible();
  await expect(analyst.getByText("overstated", { exact: true }).first()).toBeVisible();
  await analyst.getByRole("link", { name: "Review and publish" }).click();
  await expect(analyst.getByRole("heading", { name: /Publication checklist — not eligible/ })).toBeVisible();
  await expect(analyst.getByText("NON_WAIVABLE_BLOCKING_ISSUES")).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Publish this version" })).toBeDisabled();
});

test("corrected data: upload, validate and inspect", async () => {
  const cat = catalogue(CLEAN);
  await upload(analyst, CLEAN);
  versionUrl = analyst.url();
  reviewUrl = `${versionUrl}/review`;
  await expect(analyst.getByText(cat.row_counts.invoices.toLocaleString("en-US"))).toBeVisible();
  await analyst.getByRole("button", { name: "Run validation" }).click();
  await expect(analyst).toHaveURL(/\/runs\/[0-9a-f-]+$/);
  await expect(analyst.getByRole("group", { name: "Severity" }).getByRole("button", { name: /^Blocking/ })).toHaveText(/Blocking\s*1$/);
  // The data is dated inside its own period, so only planted rows are out of period.
  const outOfPeriod = analyst.getByRole("row").filter({ has: analyst.getByRole("link", { name: "INV_OUT_OF_PERIOD", exact: true }) });
  await expect(outOfPeriod.getByRole("cell").nth(3)).toHaveText(String(cat.expected_findings.INV_OUT_OF_PERIOD.rows.length));
  await expect(analyst.getByRole("link", { name: "INV_FUTURE_DATED", exact: true })).toHaveCount(0);

  await analyst.goto(reviewUrl);
  await expect(analyst.getByText("UNRESOLVED_BLOCKING_ISSUES")).toBeVisible();
  await expect(analyst.getByText("MISSING_APPROVAL")).toBeVisible();
});

test("uploading identical files creates no version; the old upload address opens the periods page", async () => {
  await analyst.goto(`/upload?period=${CLEAN}`);
  await expect(analyst).toHaveURL(new RegExp(`/periods\\?period=${CLEAN}#upload$`));
  await expect(analyst.getByLabel("Reporting period")).toHaveValue(CLEAN);
  await analyst.locator("#suppliers").setInputFiles(resolve(DATA, CLEAN, "suppliers.csv"));
  await analyst.locator("#invoices").setInputFiles(resolve(DATA, CLEAN, "invoices.csv"));
  await analyst.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(analyst.getByRole("heading", { name: `No new version: identical to SUPINV-${CLEAN}-v1` })).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Run validation" })).toBeVisible();

  await approver.goto("/upload");
  await expect(approver.getByRole("heading", { name: "Periods", exact: true })).toBeVisible();
  await expect(approver.locator("#suppliers")).toHaveCount(0);
});

test("waiver: the analyst requests, only the approver can grant", async () => {
  await analyst.goto(reviewUrl);
  await analyst.getByRole("link", { name: "INV_FK_SUPPLIER", exact: true }).click();
  const findingUrl = analyst.url();

  // Too short a justification is refused by the server.
  await analyst.getByLabel("Reason").selectOption("KNOWN_SOURCE_LIMITATION");
  await analyst.getByLabel(/Justification/).fill("too short");
  await analyst.getByRole("button", { name: "Request waiver" }).click();
  await expect(analyst.getByRole("alert").filter({ hasText: "VALIDATION_ERROR" })).toBeVisible();

  await analyst.getByLabel(/Justification/).fill("Supplier master data is loaded one day after the invoice extract.");
  await analyst.getByRole("button", { name: "Request waiver" }).click();
  await expect(analyst.getByRole("heading", { name: /Issue.*Waiver requested/ })).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Grant waiver" })).toHaveCount(0);

  await approver.goto(findingUrl);
  // Decisions are confirmed in a dialog. A denial without a comment is refused by the server.
  await approver.getByRole("button", { name: "Deny" }).click();
  await approver.getByRole("dialog").getByRole("button", { name: "Deny waiver" }).click();
  await expect(approver.getByRole("alert").filter({ hasText: "VALIDATION_ERROR" })).toBeVisible();
  await approver.getByRole("button", { name: "Grant waiver" }).click();
  await approver.getByRole("dialog").getByRole("button", { name: "Grant waiver" }).click();
  await expect(approver.getByRole("heading", { name: /Issue.*Waived/ })).toBeVisible();
  await expect(approver.getByText("Granted by Demo Approver")).toBeVisible();
});

test("review: the analyst submits, the approver must acknowledge warnings to approve", async () => {
  await approver.goto(reviewUrl);
  await expect(approver.getByText("No review request is open.")).toBeVisible();

  await analyst.goto(reviewUrl);
  await expect(analyst.getByText("MISSING_APPROVAL")).toBeVisible();
  await expect(analyst.getByText("UNRESOLVED_BLOCKING_ISSUES")).toHaveCount(0);
  await analyst.getByLabel("Note for the approver").fill("September close. One waived orphan-supplier issue.");
  await analyst.getByRole("button", { name: "Submit for review" }).click();
  await expect(analyst.getByText("Waiting for an approver's decision.")).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Approve" })).toHaveCount(0);

  await approver.reload();
  const approve = approver.getByRole("button", { name: "Approve", exact: true });
  await expect(approve).toBeDisabled();
  await approver.getByLabel(/I acknowledge the \d+ open warning/).check();
  await approve.click();
  await approver.getByRole("dialog").getByRole("button", { name: "Approve version" }).click();
  await expect(approver.getByRole("heading", { name: /Publication checklist — eligible/ })).toBeVisible();
  await expect(approver.getByText("Approved by Demo Approver")).toBeVisible();
});

test("publish, verify and export the immutable publication", async () => {
  await analyst.goto(reviewUrl);
  await analyst.getByRole("button", { name: "Publish this version" }).click();
  await analyst.getByRole("dialog").getByRole("button", { name: "Publish", exact: true }).click();
  const link = analyst.getByRole("link", { name: `PUB-SUPINV-${CLEAN}-001` }).first();
  await expect(link).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Publish this version" })).toHaveCount(0);

  await link.click();
  await expect(analyst.getByRole("heading", { name: `PUB-SUPINV-${CLEAN}-001` })).toBeVisible();
  await analyst.getByRole("button", { name: "Verify" }).click();
  await expect(analyst.getByText("VERIFIED")).toBeVisible();
  const manifestSha = (await analyst.locator("dt", { hasText: "Manifest SHA-256" }).locator("+ dd [data-value]").getAttribute("data-value")) ?? "";

  // The exported package verifies offline with the standard-library verifier.
  const download = analyst.waitForEvent("download");
  await analyst.getByRole("link", { name: "Export ZIP" }).click();
  const file = await (await download).path();
  const python = process.env.SENTINEL_PYTHON ?? resolve(REPO, "backend/.venv/bin/python");
  const output = execFileSync(python, [resolve(REPO, "scripts/verify_publication.py"), file, "--expected-manifest-sha256", manifestSha.trim()], { encoding: "utf8" });
  expect(output).toContain("VERIFIED");

  // The period list and the audit trail reflect the publication.
  await analyst.goto("/periods");
  const period = analyst.getByRole("row").filter({ has: analyst.getByRole("link", { name: CLEAN, exact: true }) });
  await expect(period.getByText("Published")).toBeVisible();
  await analyst.goto("/audit");
  await analyst.getByLabel("Event type").selectOption("DATASET_PUBLISHED");
  await expect(analyst.getByText("DATASET_PUBLISHED", { exact: true })).toBeVisible();
});

test("a second publication for the same period is refused", async () => {
  await analyst.goto(reviewUrl);
  await expect(analyst.getByText("PERIOD_ALREADY_PUBLISHED")).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Publish this version" })).toHaveCount(0);
});

test("the overview focuses on a period and the command palette jumps to it", async () => {
  await analyst.goto("/");
  const focus = analyst.getByRole("group", { name: "Focus period" });
  await focus.getByRole("button", { name: new RegExp(`^${CLEAN}`) }).click();
  await expect(focus.getByRole("button", { name: new RegExp(`^${CLEAN}`) })).toHaveAttribute("aria-pressed", "true");
  await expect(analyst.getByText(`Period ${CLEAN}`).first()).toBeVisible();

  await analyst.keyboard.press("Control+k");
  const palette = analyst.getByRole("dialog", { name: "Jump to" });
  await expect(palette).toBeVisible();
  await palette.getByRole("textbox", { name: "Search" }).fill(DIRTY);
  await expect(palette.getByRole("option", { name: new RegExp(`Period ${DIRTY}`) })).toBeVisible();
  await analyst.keyboard.press("Enter");
  await expect(analyst).toHaveURL(new RegExp(`/periods/${DIRTY}$`));
});

test("Back returns to the findings list with its filters, and browser Back and Forward agree", async () => {
  await analyst.goto("/periods");
  await analyst.getByRole("link", { name: DIRTY, exact: true }).click();
  await analyst.getByRole("link", { name: "Open current version" }).click();
  await analyst.getByRole("link", { name: "Findings", exact: true }).click();
  await analyst.getByRole("group", { name: "Severity" }).getByRole("button", { name: /^Blocking/ }).click();
  const search = analyst.getByPlaceholder("Search rule, message or column");
  await search.fill("invoices");
  await expect(analyst).toHaveURL(/severity=BLOCKING.*q=invoices|q=invoices.*severity=BLOCKING/);
  const filtered = analyst.url();

  await analyst.getByRole("link", { name: "INV_FK_SUPPLIER", exact: true }).click();
  const back = analyst.getByRole("link", { name: "Back to Findings" });
  await expect(back).toBeVisible();
  await back.click();
  await expect(analyst).toHaveURL(filtered);
  await expect(search).toHaveValue("invoices");
  await expect(analyst.getByRole("group", { name: "Severity" }).getByRole("button", { name: /^Blocking/ })).toHaveAttribute("aria-pressed", "true");

  await analyst.goForward();
  await expect(analyst).toHaveURL(/\/findings\/[0-9a-f-]+$/);
  await analyst.goBack();
  await expect(analyst).toHaveURL(filtered);

  // Primary pages have no Back button.
  await analyst.goto("/publications");
  await expect(analyst.getByRole("heading", { name: "Publications", level: 1 })).toBeVisible();
  await expect(analyst.locator(".back-btn")).toHaveCount(0);
});

test("the account menu shows the session's identity, opens the read-only profile and signs out", async ({ browser }) => {
  const page = await sessionFor(browser, "approver");
  const trigger = page.getByRole("button", { name: "Account menu for Demo Approver" });
  await trigger.click();
  const menu = page.getByRole("menu", { name: "Account" });
  await expect(menu).toContainText("@approver");
  await expect(menu).toContainText("Approver");
  await expect(menu).toContainText("No email on record");
  await menu.getByRole("menuitem", { name: "Profile and settings" }).click();
  await expect(page.getByRole("heading", { name: "Profile and settings", level: 1 })).toBeVisible();
  await expect(page.getByText("Read-only")).toBeVisible();
  // Role-based: only administrators are pointed at user management.
  await expect(page.locator("main").getByRole("link", { name: "Users" })).toHaveCount(0);

  await trigger.click();
  await page.getByRole("menuitem", { name: "Sign out" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();
  expect(await page.evaluate(() => fetch("/api/v1/session").then((r) => r.status))).toBe(401);
  await page.context().close();
});
