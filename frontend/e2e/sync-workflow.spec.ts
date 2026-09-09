import { test, expect } from "./operation-fixture";
import { source, diagnostics, run, runId } from "../tests/fixtures.mjs";
const digest = "a".repeat(64);
const row = (action: string, extra: any = {}) => ({
  action,
  object_kind: "virtualization.virtual_machines",
  external_id: "vm-1",
  name: "vm-app-01",
  reason: "Managed fields differ",
  reason_code: "GUARDED_EXECUTOR_ACTION",
  matched_object_id: 1,
  before: [["memory", 4096]],
  after: [["memory", 8192]],
  ...extra,
});
const plan = (items: any[] = []) => ({
  source_instance: "source-1",
  source_type: "proxmox",
  source_fingerprint: "s",
  target_fingerprint: "t",
  provider_fingerprint: "p",
  netbox_fingerprint: "n",
  schema_version: 1,
  planner_version: "web-5a-1",
  digest,
  apply_allowed: !items.some((i) => i.action === "BLOCKED"),
  items,
});
const retention = row("RETAIN_ONLY", {
  object_kind: "source",
  name: "Source 001",
  reason: "Objects missing from discovery are retained in NetBox.",
  before: [],
  after: [],
});
const nav = (page, name) =>
  page
    .getByRole("navigation", { name: "Source sections" })
    .getByRole("link", { name, exact: true });
async function fixture(page, value = plan([row("UPDATE"), retention])) {
  const sources = [source(), { ...source(2), enabled: true }],
    data = diagnostics(sources);
  const writes: any[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (req.method() !== "GET") writes.push({ path, body: req.postDataJSON() });
    if (path.endsWith("/operations/plan"))
      return route.fulfill({
        json: { ...value, source_instance: path.split("/")[4] },
      });
    if (path.endsWith("/sync-confirmations"))
      return route.fulfill({ json: { confirmation_token: "b".repeat(64) } });
    if (path.endsWith("/sync"))
      return route.fulfill({
        json: { status: "SUCCEEDED", plan_digest: digest, run_id: runId },
      });
    if (path.endsWith("/discovery"))
      return route.fulfill({
        json: {
          source_instance: path.split("/")[4],
          source_type: "proxmox",
          site_slug: "dc1",
          cluster_name: "Cluster 1",
          items: [
            {
              object_kind: "qemu",
              external_id: "vm-1",
              name: "VM inspection",
              classification: "REVIEW_REQUIRED",
              reason: "Unowned match",
              reason_code: "OWNERSHIP_REVIEW",
              future_action: "review",
              matched_object_id: 1,
              matched_object_name: "Existing VM",
            },
          ],
        },
      });
    if (path === "/api/v1/sources") return route.fulfill({ json: { sources } });
    if (path === "/api/v1/diagnostics") return route.fulfill({ json: data });
    if (path === "/api/v1/runs")
      return route.fulfill({ json: { runs: [run()], next_cursor: null } });
    if (path.startsWith("/api/v1/runs/")) return route.fulfill({ json: run() });
    if (path.endsWith("/schedule"))
      return route.fulfill({
        json: {
          source_instance: path.split("/")[4],
          sync_enabled: true,
          sync_interval_seconds: 600,
          scheduler_state: "WAITING",
          last_scheduled_run_at: null,
          next_expected_at: null,
        },
      });
    const found = sources.find(
      (s) => path === "/api/v1/sources/" + s.source_instance,
    );
    return route.fulfill({ status: found ? 200 : 404, json: found ?? {} });
  });
  await page.goto("/sources/source-1/sync");
  return writes;
}
async function build(page) {
  await page.getByRole("button", { name: "Build plan", exact: true }).click();
  await expect(page.getByText("Plan ready for review.")).toBeVisible();
}
async function confirm(page) {
  await page.getByRole("button", { name: "Review and confirm sync" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page
    .getByRole("button", { name: "Sync to NetBox", exact: true })
    .click();
}
test("empty and independent discovery pending/result", async ({ page }) => {
  const writes = await fixture(page);
  await expect(page.getByText("No plan yet")).toBeVisible();
  await page.screenshot({ path: "test-results/ui3-empty.png", fullPage: true });
  let release: any;
  await page.route("**/api/v1/sources/source-1/operations/discovery", async (route) => {
    await new Promise((resolve) => (release = resolve));
    await route.fallback();
  });
  await page
    .getByRole("button", { name: "Run discovery", exact: true })
    .click();
  await expect(page.getByText(/Run discovery.*Operation in progress/)).toBeVisible();
  await page.screenshot({
    path: "test-results/ui3-discovery-pending.png",
    fullPage: true,
  });
  release();
  await expect(page.getByText(/Discovery received/)).toBeVisible();
  await page.getByText("VM inspection", { exact: true }).click();
  await expect(page.getByText("NetBox match: Existing VM")).toBeVisible();
  await page.screenshot({
    path: "test-results/ui3-discovery-result.png",
    fullPage: true,
  });
  expect(writes.filter((w) => w.path.endsWith("/operations/plan"))).toHaveLength(0);
  await build(page);
});
test("mixed operation counts, default filters and exact two-way diff", async ({
  page,
}) => {
  await fixture(
    page,
    plan([
      row("CREATE", {
        name: "new-vm",
        before: [],
        after: [["name", "new-vm"]],
      }),
      row("UPDATE"),
      row("REVIEW_REQUIRED", {
        name: "needs-review",
        before: [],
        after: [],
        reason: "Foreign ownership requires review",
      }),
      retention,
      ...Array.from({ length: 105 }, (_, i) =>
        row("NO_CHANGE", { name: "unchanged-" + i, before: [], after: [] }),
      ),
    ]),
  );
  await build(page);
  await expect(
    page.getByRole("button", { name: "Changes", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("unchanged-0", { exact: true })).toHaveCount(0);
  await expect(page.locator(".sync-summary").first()).toContainText(
    "Unchanged rows105",
  );
  await page.getByText("vm-app-01", { exact: true }).click();
  await expect(
    page.getByRole("table", { name: "Managed fields for vm-app-01" }),
  ).toContainText("4096");
  await expect(
    page.getByRole("table", { name: "Managed fields for vm-app-01" }),
  ).toContainText("8192");
  await page.screenshot({ path: "test-results/ui3-mixed.png", fullPage: true });
  await page.getByRole("button", { name: "Attention", exact: true }).click();
  await expect(page.getByText("needs-review", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review and confirm sync" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await page
    .getByRole("combobox", { name: "Action", exact: true })
    .selectOption("NO_CHANGE");
  await expect(
    page.getByText("105 rows in this view · showing first 50"),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/ui3-unchanged.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Show 50 more rows" }).click();
  await expect(
    page.getByText("105 rows in this view · showing first 100"),
  ).toBeVisible();
});
test("blocked defaults to Attention and never opens confirmation", async ({
  page,
}) => {
  const writes = await fixture(
    page,
    plan([
      row("BLOCKED", { reason: "Foreign IP ownership", name: "blocked-vm" }),
      retention,
    ]),
  );
  await build(page);
  await expect(
    page.getByRole("button", { name: "Attention", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "Review and confirm sync" }),
  ).toBeDisabled();
  await page.getByText("blocked-vm", { exact: true }).click();
  await page.screenshot({
    path: "test-results/ui3-blocked.png",
    fullPage: true,
  });
  expect(
    writes.filter((w) => w.path.endsWith("/sync-confirmations")),
  ).toHaveLength(0);
});
test("review allowed, keyboard modal trap/cancel/return and digest/token exactness", async ({
  page,
}) => {
  const writes = await fixture(
    page,
    plan([
      row("UPDATE"),
      row("REVIEW_REQUIRED", { name: "review-row" }),
      retention,
    ]),
  );
  await build(page);
  const open = page.getByRole("button", { name: "Review and confirm sync" });
  await open.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    dialog.getByRole("button", { name: "Sync to NetBox" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await page.screenshot({
    path: "test-results/ui3-confirmation.png",
    fullPage: true,
  });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(open).toBeFocused();
  await confirm(page);
  await expect(page.locator(".sync-result")).toContainText("Sync completed");
  expect(
    writes.find((w) => w.path.endsWith("/sync-confirmations")).body,
  ).toEqual({ plan_digest: digest, confirmed: true, operation_id: expect.stringMatching(/^[a-f0-9-]{36}$/) });
  expect(writes.find((w) => w.path.endsWith("/sync")).body).toEqual({
    confirmation_token: "b".repeat(64),
    operation_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
  });
  await expect(
    page.getByRole("link", { name: "Open run", exact: true }),
  ).toHaveAttribute("href", "/runs/" + runId);
  await page.screenshot({
    path: "test-results/ui3-success.png",
    fullPage: true,
  });
  await nav(page, "Schedule").click();
  await expect(nav(page, "Schedule")).toHaveAttribute("aria-current", "page");
  await nav(page, "Sync").click();
  await expect(
    page.getByRole("heading", { name: "Sync completed", exact: true }),
  ).toBeVisible();
});
for (const [status, label] of [
  ["SUCCEEDED", "Sync completed"],
  ["FAILED_BEFORE_WRITE", "Failed before write"],
  ["PARTIALLY_APPLIED", "Partially applied"],
  ["OUTCOME_UNCERTAIN", "Outcome unknown"],
])
  test("apply DTO outcome " + status, async ({ page }) => {
    await fixture(page);
    await page.route("**/api/v1/sources/source-1/sync", (route) =>
      route.fulfill({ json: { status, plan_digest: digest } }),
    );
    await build(page);
    await confirm(page);
    await expect(
      page.getByRole("heading", { name: label, exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Open run", exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Review and confirm sync" }),
    ).toBeDisabled();
    if (status === "OUTCOME_UNCERTAIN")
      await page.screenshot({
        path: "test-results/ui3-uncertain.png",
        fullPage: true,
      });
  });
for (const [code, label] of [
  ["APPLY_LOCKED", "Sync did not start"],
  ["PLAN_BLOCKED", "Blocked"],
  ["PLAN_STALE", "Stale plan"],
  ["APPLY_FAILED", "Request failed"],
  ["APPLY_UNAVAILABLE", "Outcome unknown"],
])
  test("apply error " + code, async ({ page }) => {
    await fixture(page);
    await page.route("**/api/v1/sources/source-1/sync", (route) =>
      route.fulfill({
        status: 409,
        json: { error: { code, message: "RAW SECRET" } },
      }),
    );
    await build(page);
    await confirm(page);
    await expect(
      page.getByRole("heading", { name: label, exact: true }),
    ).toBeVisible();
    await expect(page.getByText("RAW SECRET")).toHaveCount(0);
    await expect(
      page.getByRole("button", { name: "Review and confirm sync" }),
    ).toBeDisabled();
    if (code === "PLAN_STALE")
      await page.screenshot({
        path: "test-results/ui3-stale.png",
        fullPage: true,
      });
  });
test("stale at prepare never submits apply", async ({ page }) => {
  const writes = await fixture(page);
  await page.route("**/api/v1/sources/source-1/sync-confirmations", (route) =>
    route.fulfill({ status: 409, json: { error: { code: "PLAN_STALE" } } }),
  );
  await build(page);
  await confirm(page);
  await expect(
    page.getByRole("heading", { name: "Stale plan", exact: true }),
  ).toBeVisible();
  expect(writes.filter((w) => w.path.endsWith("/sync"))).toHaveLength(0);
});
test("network loss after apply remains uncertain", async ({ page }) => {
  await fixture(page);
  await page.route("**/api/v1/sources/source-1/sync", (route) =>
    route.abort("connectionreset"),
  );
  await build(page);
  await confirm(page);
  await expect(
    page.getByRole("heading", { name: "Outcome unknown", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(/Client\/network response was lost/),
  ).toBeVisible();
});
test("duplicate clicks do not duplicate planning or apply", async ({
  page,
}) => {
  const writes = await fixture(page);
  let releasePlan: any, releaseApply: any;
  await page.route("**/api/v1/sources/source-1/operations/plan", async (route) => {
    await new Promise((resolve) => (releasePlan = resolve));
    await route.fallback();
  });
  await page
    .getByRole("button", { name: "Build plan", exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click();
      button.click();
    });
  await expect(
    page.getByRole("button", { name: "Build plan", exact: true }),
  ).toBeDisabled();
  releasePlan();
  await expect(page.getByText("Plan ready for review.")).toBeVisible();
  await page.route("**/api/v1/sources/source-1/sync", async (route) => {
    await new Promise((resolve) => (releaseApply = resolve));
    await route.fallback();
  });
  await page.getByRole("button", { name: "Review and confirm sync" }).click();
  await page
    .getByRole("button", { name: "Sync to NetBox" })
    .evaluate((button: HTMLButtonElement) => {
      button.click();
      button.click();
    });
  await expect(
    page.getByRole("dialog").getByText(/Sync to NetBox.*Waiting for server acknowledgement/),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeVisible();
  releaseApply();
  await expect(
    page.getByRole("heading", { name: "Sync completed", exact: true }),
  ).toBeVisible();
  expect(writes.filter((w) => w.path.endsWith("/operations/plan"))).toHaveLength(1);
  expect(writes.filter((w) => w.path.endsWith("/sync"))).toHaveLength(1);
});
for (const stage of ["sync-confirmations", "sync"])
  test(
    "late " + stage + " stays isolated after source switch",
    async ({ page }) => {
      const writes = await fixture(page);
      let release: any;
      await page.route("**/api/v1/sources/source-1/" + stage, async (route) => {
        await new Promise((resolve) => (release = resolve));
        await route.fallback();
      });
      await build(page);
      await confirm(page);
      await expect(
        page
          .getByRole("dialog")
          .getByRole("button", { name: "Sync to NetBox" }),
      ).toBeDisabled();
      // Simulate a browser-history route change while the modal is pending.
      await page.evaluate(() => {
        history.pushState({}, "", "/sources/source-2/sync");
        dispatchEvent(new PopStateEvent("popstate"));
      });
      await expect(
        page.getByRole("heading", { name: "Source 002", exact: true }),
      ).toBeVisible();
      release();
      await expect(page.getByText("No plan yet")).toBeVisible();
      await expect(
        page.getByRole("heading", { name: "Sync completed", exact: true }),
      ).toHaveCount(0);
      if (stage === "sync-confirmations")
        expect(writes.filter((w) => w.path.endsWith("/sync"))).toHaveLength(0);
    },
  );
for (const width of [1440, 1280, 1024, 768])
  test("diff and dialog layout " + width, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await fixture(
      page,
      plan([
        row("UPDATE", {
          before: [
            ["memory", 4096],
            ["custom_fields", { ownership: "x".repeat(300) }],
          ],
          after: [
            ["memory", 8192],
            ["custom_fields", { ownership: "y".repeat(300) }],
          ],
        }),
        retention,
      ]),
    );
    await build(page);
    await page.getByText("vm-app-01", { exact: true }).click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: "test-results/ui3-diff-" + width + ".png",
      fullPage: true,
    });
    await page.getByRole("button", { name: "Review and confirm sync" }).click();
    const box = await page.getByRole("dialog").boundingBox();
    expect(box!.width).toBeLessThanOrEqual(width);
    await page.screenshot({
      path: "test-results/ui3-dialog-" + width + ".png",
      fullPage: true,
    });
  });

test("failed rebuild preserves previous evidence but cannot apply it", async ({
  page,
}) => {
  await fixture(page);
  await build(page);
  await page.route("**/api/v1/sources/source-1/operations/plan", (route) =>
    route.fulfill({
      status: 503,
      json: { error: { code: "REGISTRY_UNAVAILABLE", message: "RAW SECRET" } },
    }),
  );
  await page.getByRole("button", { name: "Rebuild plan", exact: true }).click();
  await expect(
    page.getByText("Source registry is unavailable.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("vm-app-01", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Review and confirm sync" }),
  ).toBeDisabled();
  await expect(page.getByText("RAW SECRET")).toHaveCount(0);
});
test("uncertain outcome stays visible while a new plan is built", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/sources/source-1/sync", (route) =>
    route.fulfill({
      json: { status: "OUTCOME_UNCERTAIN", plan_digest: digest },
    }),
  );
  await build(page);
  await confirm(page);
  await expect(
    page.getByRole("heading", { name: "Outcome unknown", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Rebuild plan", exact: true }).click();
  await expect(page.getByText("Plan ready for review.")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Outcome unknown", exact: true }),
  ).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage))).toEqual([]);
  expect(page.url()).not.toContain(digest);
});
test("keyboard row expansion preserves missing values and unusual endpoint kinds", async ({
  page,
}) => {
  await fixture(
    page,
    plan([
      row("CREATE", {
        name: "new-object",
        object_kind: "unusual.endpoint",
        matched_object_id: null,
        before: [],
        after: [
          ["name", "new-object"],
          ["empty", null],
        ],
      }),
      row("REVIEW_REQUIRED", { name: "no-fields", before: [], after: [] }),
      retention,
    ]),
  );
  await build(page);
  const summary = page
    .locator(".plan-row > summary")
    .filter({ hasText: "new-object" });
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("table", { name: "Managed fields for new-object" }),
  ).toContainText("Not provided");
  await expect(
    page.getByRole("table", { name: "Managed fields for new-object" }),
  ).toContainText("null");
  await page.getByRole("button", { name: "Attention", exact: true }).click();
  await page.getByText("no-fields", { exact: true }).click();
  await expect(
    page.getByText(
      "No managed before/proposed values were provided for this row.",
    ),
  ).toBeVisible();
});
test("switching sibling tab dismisses unsubmitted confirmation and preserves plan", async ({
  page,
}) => {
  const writes = await fixture(page);
  await build(page);
  await page.getByRole("button", { name: "Review and confirm sync" }).click();
  await page.evaluate(() => {
    history.pushState({}, "", "/sources/source-1/schedule");
    dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await nav(page, "Sync").click();
  await expect(page.getByText("Plan ready for review.")).toBeVisible();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect(
    writes.filter((w) => w.path.endsWith("/sync-confirmations")),
  ).toHaveLength(0);
});
