import {previewResult,installCatalog,selectPlacement} from './source-placement-fixture';
import { installOperationFixtures } from './operation-fixture';
import { test, expect, chromium } from "./operation-fixture";
import { mkdtemp, mkdir, writeFile, rm, realpath } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  source,
  diagnostics,
  run,
  runId,
  staleWarning,
} from "../tests/fixtures.mjs";
const digest = "a".repeat(64);
const row = (action = "UPDATE", extra = {}) => ({
  action,
  object_kind: "virtualization.virtual_machines",
  external_id: "vm-1",
  name: "app-01",
  reason: "Managed fields differ",
  reason_code: "GUARDED_EXECUTOR_ACTION",
  matched_object_id: 1,
  before: [["memory", 4096]],
  after: [["memory", 8192]],
  ...extra,
});
export const mixedPlan = {
  source_instance: "source-1",
  source_type: "proxmox",
  source_fingerprint: "s",
  target_fingerprint: "t",
  provider_fingerprint: "p",
  netbox_fingerprint: "n",
  schema_version: 1,
  planner_version: "web-5a-1",
  digest,
  apply_allowed: true,
  items: [
    row(),
    row("CREATE", { name: "app-02", external_id: "vm-2", before: [] }),
    row("REVIEW_REQUIRED", {
      name: "unowned-vm",
      external_id: "vm-3",
      reason: "Ownership needs review",
    }),
    row("RETAIN_ONLY", {
      object_kind: "source",
      external_id: "source-1",
      name: "Source 001",
      reason: "Missing objects are retained",
      before: [],
      after: [],
    }),
  ],
};
async function fixture(page, options: any = {}) {
  const sources = Array.from({ length: options.count ?? 3 }, (_, i) =>
    source(i + 1),
  );
  if (options.long)
    sources[0].name = "Source with a very long operational name ".repeat(8);
  const d = diagnostics(sources);
  const state = {
    outcome: "SUCCEEDED",
    degraded: false,
    fail: false,
    empty: false,
    stale: false,
    conflict: false,
  };
  const requests: any[] = [];
  const schedules = new Map(
    sources.map((s) => [
      s.source_instance,
      {
        source_instance: s.source_instance,
        sync_enabled: s.sync_enabled,
        sync_interval_seconds: 600,
        scheduler_state: "WAITING",
        last_scheduled_run_at: null,
        next_expected_at: null,
      },
    ]),
  );
  const records = Array.from({ length: options.count ?? 3 }, (_, i) => ({
    ...run(),
    run_id:
      i === 0
        ? runId
        : "22222222-2222-4222-8222-" + String(i).padStart(12, "0"),
  }));
  await page.route("**/api/v1/**", async (route) => {
    const req = route.request(),
      url = new URL(req.url()),
      p = url.pathname;
    requests.push({
      path: p,
      method: req.method(),
      body: req.method() === "GET" ? null : req.postDataJSON(),
    });
    if (state.fail && req.method() === "GET")
      return route.fulfill({ status: 503, json: {} });
    if (p.endsWith("/test-connection"))
      return route.fulfill({
        json: previewResult,
      });
    if (p.endsWith("/cancel-onboarding"))
      return route.fulfill({ json: { status: "cancelled" } });
    if (p === "/api/v1/sources" && req.method() === "POST") {
      const body = req.postDataJSON();
      const created = {
        ...source(),
        ...body,
        type: body.source_type,
        enabled: true,
        sync_enabled: false,
        legacy_identity_owner: false,
        status: "sync_disabled",
      };
      delete created.onboarding_token;
      sources.push(created);
      return route.fulfill({ json: created });
    }
    if (p.endsWith("/operations/plan"))
      return route.fulfill({
        json: {
          ...mixedPlan,
          items: options.long
            ? [
                row("UPDATE", {
                  name: "VeryLongVMName".repeat(40),
                  reason: "Safe ownership evidence ".repeat(60),
                }),
              ]
            : mixedPlan.items,
        },
      });
    if (p.endsWith("/sync-confirmations"))
      return state.stale
        ? route.fulfill({
            status: 409,
            json: { error: { code: "PLAN_STALE", message: "Plan changed" } },
          })
        : route.fulfill({ json: { confirmation_token: "c".repeat(64) } });
    if (p.endsWith("/sync"))
      return route.fulfill({
        json: { status: state.outcome, plan_digest: digest, run_id: runId },
      });
    if (p.endsWith("/schedule")) {
      const key = p.split("/")[4],
        s = schedules.get(key);
      if (req.method() === "PATCH") {
        if (state.conflict)
          return route.fulfill({
            status: 409,
            json: { error: { code: "SCHEDULE_CONFLICT", message: "Changed" } },
          });
        Object.assign(s, {
          sync_enabled: req.postDataJSON().sync_enabled,
          sync_interval_seconds: req.postDataJSON().sync_interval_seconds,
        });
      }
      return route.fulfill({ json: s });
    }
    if (p === "/api/v1/sources")
      return route.fulfill({ json: { sources: state.empty ? [] : sources } });
    if (p === "/api/v1/diagnostics")
      return route.fulfill({
        json: state.degraded
          ? {
              ...d,
              overall_status: "DEGRADED",
              stale_runs: [staleWarning],
              warnings: [staleWarning],
              sources: d.sources.map((s, i) =>
                i === 0
                  ? {
                      ...s,
                      status: "DEGRADED",
                      warnings: ["STALE_RUNNING"],
                      warning_count: 1,
                    }
                  : s,
              ),
            }
          : d,
      });
    if (p === "/api/v1/runs") {
      const offset = url.searchParams.has("cursor")
          ? records.findIndex(
              (r) => r.run_id === url.searchParams.get("cursor"),
            ) + 1
          : 0,
        rows = state.empty ? [] : records.slice(offset, offset + 50);
      return route.fulfill({
        json: {
          runs: rows,
          next_cursor: rows.length === 50 ? rows.at(-1).run_id : null,
        },
      });
    }
    if (p.startsWith("/api/v1/runs/"))
      return route.fulfill({ json: { ...records[0], status: state.outcome } });
    const found = sources.find(
      (s) => p === "/api/v1/sources/" + s.source_instance,
    );
    return route.fulfill({ status: found ? 200 : 404, json: found ?? {} });
  });
  return { state, requests };
}
const themes = ["light", "dark"] as const;
async function build(page) {
  await page.getByRole("button", { name: "Build plan", exact: true }).click();
  await expect(
    page.getByText("Plan ready for review.", { exact: true }),
  ).toBeVisible();
}
async function apply(page) {
  await page.getByRole("button", { name: "Review and confirm sync" }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Sync to NetBox", exact: true })
    .click();
}
async function overflow(page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
}
for (const theme of themes)
  for (const width of [1440, 1280, 1024, 768])
    test(
      "UI-5 full visual gallery " + theme + " " + width,
      async ({ page }) => {
        await page.setViewportSize({ width, height: 960 });
        await page.emulateMedia({ colorScheme: theme });
        const f = await fixture(page);
        const screens = [
          ["/", "overview"],
          ["/sources", "sources"],
          ["/sources/source-1", "source-overview"],
          ["/sources/source-1/runs", "source-runs"],
          ["/sources/source-1/schedule", "schedule"],
          ["/sources/source-1/diagnostics", "source-diagnostics"],
          ["/sources/source-1/configuration", "configuration"],
          ["/runs", "runs"],
          ["/runs/" + runId, "run-detail"],
          ["/diagnostics", "diagnostics-healthy"],
          ["/sources/add", "add-source"],
        ];
        for (const [route, name] of screens) {
          await page.goto(route);
          await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
          await expect(
            page.getByRole("status").filter({ hasText: /^Loading/ }),
          ).toHaveCount(0);
          await expect(page.locator(":root")).toHaveAttribute(
            "data-theme",
            theme,
          );
          await overflow(page);
          await page.screenshot({
            path: `test-results/ui5-${theme}-${width}-${name}.png`,
            fullPage: true,
          });
        }
        await page.goto("/sources/source-1/sync");
        await build(page);
        await page.locator(".plan-row > summary").first().click();
        await overflow(page);
        await page.screenshot({
          path: `test-results/ui5-${theme}-${width}-sync-plan.png`,
          fullPage: true,
        });
        await page
          .getByRole("button", { name: "Review and confirm sync" })
          .click();
        await expect(
          page
            .getByRole("dialog")
            .getByRole("button", { name: "Cancel", exact: true }),
        ).toBeFocused();
        await page.screenshot({
          path: `test-results/ui5-${theme}-${width}-confirmation.png`,
        });
        f.state.outcome = "OUTCOME_UNCERTAIN";
        await page
          .getByRole("dialog")
          .getByRole("button", { name: "Sync to NetBox", exact: true })
          .click();
        await expect(
          page.getByRole("heading", { name: "Outcome unknown", exact: true }),
        ).toBeVisible();
        await page.screenshot({
          path: `test-results/ui5-${theme}-${width}-sync-uncertain.png`,
          fullPage: true,
        });
        f.state.degraded = true;
        await page.goto("/diagnostics");
        await expect(page.locator(".diagnostic-attention")).toContainText(
          "Completion unconfirmed",
        );
        await page.screenshot({
          path: `test-results/ui5-${theme}-${width}-diagnostics-degraded.png`,
          fullPage: true,
        });
        f.state.empty = true;
        await page.goto("/runs");
        await expect(
          page.getByText("No runs have been recorded yet."),
        ).toBeVisible();
        await page.screenshot({
          path: `test-results/ui5-${theme}-${width}-empty.png`,
          fullPage: true,
        });
        f.state.fail = true;
        await page
          .getByRole("button", { name: "Refresh", exact: true })
          .click();
        await expect(page.getByRole("alert").first()).toContainText(
          "Could not refresh",
        );
        await page.screenshot({
          path: `test-results/ui5-${theme}-${width}-refresh-error.png`,
          fullPage: true,
        });
      },
    );
test("themes follow system, persist explicit choice, and do not refetch resources", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/diagnostics");
  await expect(page.locator("#component-api")).toBeVisible();
  await expect(page.locator(":root")).toHaveAttribute("data-theme", "dark");
  const calls = f.requests.length;
  await page
    .getByRole("combobox", { name: "Theme", exact: true })
    .selectOption("light");
  await expect(page.locator(":root")).toHaveAttribute("data-theme", "light");
  expect(f.requests.length).toBe(calls);
  await page.reload();
  await expect(page.locator(":root")).toHaveAttribute("data-theme", "light");
  await page
    .getByRole("combobox", { name: "Theme", exact: true })
    .selectOption("system");
  await expect(page.locator(":root")).toHaveAttribute("data-theme", "dark");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(page.locator(":root")).toHaveAttribute("data-theme", "light");
  await page.evaluate(() =>
    localStorage.setItem("netbox-sync.theme", "invalid"),
  );
  await page.reload();
  await expect(
    page.getByRole("combobox", { name: "Theme", exact: true }),
  ).toHaveValue("system");
});
test("theme works when browser storage is unavailable", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      get() {
        throw new Error("Blocked");
      },
    });
  });
  await fixture(page);
  await page.goto("/");
  await page
    .getByRole("combobox", { name: "Theme", exact: true })
    .selectOption("dark");
  await expect(page.locator(":root")).toHaveAttribute("data-theme", "dark");
});
test("keyboard operator journey navigates attention, tabs, plan, dialog and result", async ({
  page,
}) => {
  const f = await fixture(page);
  f.state.degraded = true;
  await page.goto("/");
  await expect(page.locator(".overview-summary")).toContainText(
    "Needs attention",
  );
  const attention = page
    .getByRole("link", { name: "Source 001", exact: true })
    .first();
  await attention.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/source-1$/);
  await expect(page.locator("#content")).toBeFocused();
  const sync = page
    .getByRole("navigation", { name: "Source sections" })
    .getByRole("link", { name: "Sync", exact: true });
  await sync.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#content")).toBeFocused();
  await page.getByRole("button", { name: "Build plan", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Plan ready for review.")).toBeVisible();
  await page.locator(".plan-row > summary").first().focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("table", { name: "Managed fields for app-01" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review and confirm sync" }).focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    dialog.getByRole("button", { name: "Sync to NetBox", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Sync completed", exact: true }),
  ).toBeVisible();
});
test("narrow navigation supports Escape and route focus without trapping sidebar", async ({
  page,
}) => {
  await fixture(page);
  await page.setViewportSize({ width: 768, height: 500 });
  await page.goto("/");
  await page.getByRole("button", { name: "Navigation", exact: true }).click();
  const link = page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Runs", exact: true });
  await link.focus();
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("button", { name: "Navigation", exact: true }),
  ).toBeFocused();
  await expect(link).toBeHidden();
  await page.getByRole("button", { name: "Navigation", exact: true }).click();
  await link.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/runs$/);
  await expect(page.locator("#content")).toBeFocused();
});
test("existing Add Source journey clears credentials, focuses review and links registered source", async ({
  page,
}) => {
  const f = await fixture(page);
  await installCatalog(page);
  await page.goto("/sources/add");
  await page
    .getByRole("textbox", { name: "Hostname or IPv4 address" })
    .fill("host.example.test");
  await page.getByLabel("Token user (user@realm)").fill("user@realm");
  await page.getByLabel("Token name (without user prefix)").fill("test-token");
  await page.getByLabel("Token secret").fill("FAKE-SECRET");
  await page
    .getByRole("button", { name: "Test Connection", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Review source details", exact: true }),
  ).toBeFocused();
  await expect(page.locator('input[name="secret"]')).toHaveCount(0);
  await selectPlacement(page);
  await page
    .getByRole("checkbox", {
      name: "Register a new source with automatic sync OFF.",
    })
    .check();
  await page
    .getByRole("button", { name: "Register Source", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Source registered", exact: true }),
  ).toBeFocused();
  const writes = f.requests.filter((r) => r.method === "POST");
  expect(writes.map((r) => r.path)).toEqual([
    "/api/v1/sources/test-connection",
    "/api/v1/sources",
  ]);
  expect(writes[1].body.confirm_sync_disabled).toBe(true);
  expect(writes[1].body.secret).toBeUndefined();
  await page.getByRole("link", { name: "Open source", exact: true }).click();
  await expect(page).toHaveURL(new RegExp("sources/"+previewResult.suggested_source_instance+"$"));
});
test("long names, reasons and narrow height preserve dialog controls and reflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 720, height: 400 });
  await fixture(page, { long: true });
  await page.goto("/sources/source-1/sync");
  await build(page);
  await overflow(page);
  await page.locator(".plan-row > summary").first().click();
  await overflow(page);
  await page.getByRole("button", { name: "Review and confirm sync" }).click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "Cancel", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    dialog.getByRole("button", { name: "Sync to NetBox", exact: true }),
  ).toBeFocused();
  const bounds = await dialog
    .getByRole("button", { name: "Sync to NetBox", exact: true })
    .boundingBox();
  expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(400);
  await page.screenshot({ path: "test-results/ui5-long-narrow-dialog.png" });
});
test("100+ fixtures retain bounded rendering and full source pagination", async ({
  page,
}) => {
  const f = await fixture(page, { count: 125 });
  const start = Date.now();
  await page.goto("/sources?size=100");
  await expect(page.locator("tbody tr")).toHaveCount(100);
  await overflow(page);
  await page.goto("/runs");
  await expect(page.locator(".run-table tbody tr")).toHaveCount(50);
  await page.getByRole("button", { name: "Older runs" }).click();
  await expect(page.locator(".run-table tbody tr")).toHaveCount(50);
  await page.getByRole("button", { name: "Older runs" }).click();
  await expect(page.locator(".run-table tbody tr")).toHaveCount(25);
  test
    .info()
    .annotations.push({
      type: "render-observation",
      description: `125 fixture records, 100 source rows and 50/50/25 run pages: ${Date.now() - start} ms including navigation; ${f.requests.length} API requests.`,
    });
});
test("native Chromium 200 percent zoom reflows the app", async () => {
  const profile = await mkdtemp(path.join(tmpdir(), "netbox-sync-ui5-zoom-"));
  let context;
  try {
    await mkdir(path.join(profile, "Default"));
    await writeFile(
      path.join(profile, "Default", "Preferences"),
      JSON.stringify({
        // Chromium stores default zoom by storage partition; x is the default.
        partition: { default_zoom_level: { x: Math.log(2) / Math.log(1.2) } },
      }),
    );
    context = await chromium.launchPersistentContext(profile, {
      channel: "chromium",
      headless: true,
      viewport: null,
      args: ["--window-size=1440,900"],
    });
    const page = context.pages()[0];
    installOperationFixtures(page);
    await fixture(page);
    for (const route of ["/", "/sources", "/sources/source-1", "/sources/source-1/runs", "/sources/source-1/schedule", "/sources/source-1/diagnostics", "/sources/source-1/configuration", "/runs", "/runs/" + runId, "/diagnostics", "/sources/add"]) {
      await page.goto("http://127.0.0.1:5179" + route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByRole("status").filter({ hasText: /^Loading/ })).toHaveCount(0);
      await overflow(page);
    }
    await page.goto("http://127.0.0.1:5179/sources/source-1/sync");
    await build(page);
    const metrics = await page.evaluate(() => ({
      width: innerWidth,
      ratio: devicePixelRatio,
    }));
    expect(metrics.ratio).toBeGreaterThanOrEqual(1.99);
    expect(metrics.width).toBeLessThanOrEqual(720);
    await overflow(page);
    await page.getByRole("button", { name: "Review and confirm sync" }).click();
    await expect(
      page
        .getByRole("dialog")
        .getByRole("button", { name: "Cancel", exact: true }),
    ).toBeFocused();
    await expect(page.getByRole("dialog")).toBeInViewport();
    const cdp = await context.newCDPSession(page);
    const capture = await cdp.send("Page.captureScreenshot", {
      format: "png", fromSurface: true, captureBeyondViewport: false,
    });
    await writeFile("test-results/ui5-native-200-percent-zoom.png", Buffer.from(capture.data, "base64"));
  } finally {
    await context?.close();
    const resolved = await realpath(profile),
      root = await realpath(tmpdir());
    if (
      path.dirname(resolved) !== root ||
      !path.basename(resolved).startsWith("netbox-sync-ui5-zoom-")
    )
      throw new Error("Unexpected profile cleanup target");
    await rm(resolved, { recursive: true });
  }
});
for (const theme of themes)
  test("semantic text and control contrast " + theme, async ({ page }) => {
    await fixture(page);
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await page.goto("/");
    const tokens = await page.evaluate(() => {
      const style = getComputedStyle(document.documentElement);
      return Object.fromEntries(
        [
          "text",
          "muted",
          "surface",
          "surface-muted",
          "accent",
          "on-accent",
          "success",
          "success-bg",
          "warning",
          "warning-bg",
          "danger",
          "danger-bg",
          "info",
          "info-bg",
          "nav-text",
          "nav-surface",
          "nav-accent",
          "nav-active",
          "control-border",
          "surface-raised",
        ].map((k) => [k, style.getPropertyValue("--" + k).trim()]),
      );
    });
    function luminance(hex: string) {
      const channels = hex
        .replace("#", "")
        .match(/../g)!
        .map((v) => parseInt(v, 16) / 255)
        .map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    }
    function contrast(a: string, b: string) {
      const x = luminance(a),
        y = luminance(b);
      return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
    }
    for (const [fg, bg] of [
      ["text", "surface"],
      ["muted", "surface-muted"],
      ["accent", "surface"],
      ["on-accent", "accent"],
      ["success", "success-bg"],
      ["warning", "warning-bg"],
      ["danger", "danger-bg"],
      ["info", "info-bg"],
      ["nav-text", "nav-surface"],
      ["nav-accent", "nav-active"],
    ])
      expect(
        contrast(tokens[fg], tokens[bg]),
        fg + "/" + bg,
      ).toBeGreaterThanOrEqual(4.5);
    expect(
      contrast(tokens["control-border"], tokens["surface-raised"]),
    ).toBeGreaterThanOrEqual(3);
    expect(
      await page.evaluate(
        () => matchMedia("(prefers-reduced-motion: reduce)").matches,
      ),
    ).toBe(true);
  });

for (const scenario of ["exact", "foreign source", "unavailable history"]) {
  test("Overview and Sources use exact stale evidence: " + scenario, async ({ page }) => {
    await fixture(page);
    const data = diagnostics([source()]);
    data.sources[0].latest_run = run("RUNNING");
    data.sources[0].warnings = ["STALE_RUNNING"];
    data.sources[0].warning_count = 1;
    data.stale_runs = [{ ...staleWarning, source_instance: scenario === "foreign source" ? "source-2" : "source-1" }];
    if (scenario === "unavailable history") data.components.run_history.status = "UNAVAILABLE";
    await page.route("**/api/v1/diagnostics", route => route.fulfill({ json: data }));
    await page.route("**/api/v1/runs?*", route => route.fulfill({ json: { runs: [run("RUNNING")], next_cursor: null } }));
    await page.goto("/");
    await expect(page.getByRole("table").locator(".badge").filter({ hasText: scenario === "exact" ? "Completion unconfirmed" : "Recorded as running" })).toBeVisible();
    await page.goto("/sources");
    const table = page.getByRole("table");
    if (scenario === "unavailable history") {
      await expect(table.locator(".badge").filter({ hasText: "Recorded as running" })).toHaveCount(0);
      await expect(table.locator(".badge").filter({ hasText: "Completion unconfirmed" })).toHaveCount(0);
    } else {
      await expect(table.locator(".badge").filter({ hasText: scenario === "exact" ? "Completion unconfirmed" : "Recorded as running" })).toBeVisible();
    }
    const skip = page.locator(".skip-link");
    await expect(skip).toHaveCSS("clip-path", "inset(50%)");
    await skip.focus();
    await expect(skip).toHaveCSS("clip-path", "none");
    await expect(skip).toBeInViewport();
  });
}

for(const theme of themes)for(const width of [1440,390])test(`shared RU full-page gallery ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:960});await page.emulateMedia({colorScheme:theme,reducedMotion:'reduce'});
 const f=await fixture(page,{long:true});
 await page.goto('/');await page.getByLabel('Language / Язык').focus();await page.getByLabel('Language / Язык').selectOption('ru');
 await expect(page.getByLabel('Language / Язык')).toBeFocused();
 for(const [route,name] of [['/','overview'],['/sources','sources'],['/sources/source-1','source'],['/sources/source-1/schedule','schedule'],['/sources/source-1/configuration','configuration'],['/runs','runs'],['/runs/'+runId,'run'],['/diagnostics','diagnostics'],['/system','system'],['/sources/add','add']]){
  await page.goto(route);await expect(page.getByRole('heading',{level:1})).toBeVisible();await overflow(page);
  await expect(page.locator('html')).toHaveAttribute('lang','ru');
  await expect(page.getByRole('status').filter({hasText:/^Загрузка/})).toHaveCount(0);
  await page.screenshot({path:`test-results/ux-ru-${theme}-${width}-${name}.png`,fullPage:true});
 }
 await page.goto('/sources/source-1/sync');await page.getByRole('button',{name:'Построить план',exact:true}).click();
 await expect(page.locator('.plan-row').first()).toBeVisible();await overflow(page);
 await page.screenshot({path:`test-results/ux-ru-${theme}-${width}-plan.png`,fullPage:true});
 f.state.outcome='PARTIALLY_APPLIED';await page.getByRole('button',{name:'Проверить и подтвердить синхронизацию'}).click();
 await page.getByRole('dialog').getByRole('button',{name:'Синхронизировать с NetBox',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Частично применено',exact:true})).toBeVisible();
 await page.screenshot({path:`test-results/ux-ru-${theme}-${width}-partial.png`,fullPage:true});
 await page.reload();await expect(page.locator('html')).toHaveAttribute('lang','ru');
});

// Ordinary operator content is a separate gallery from adversarial long-name fixtures.
for(const lang of ['en','ru'])for(const theme of themes)for(const width of [1440,390])
test(`Overview editorial ordinary ${lang} ${theme} ${width}`,async({page})=>{
 await page.setViewportSize({width,height:960});await page.emulateMedia({colorScheme:theme,reducedMotion:'reduce'});
 await fixture(page);
 const ordinary=diagnostics([source(),source(2),source(3)]);ordinary.generated_at=new Date().toISOString();ordinary.sources[0].next_expected_at=new Date(Date.now()+600000).toISOString();
 await page.route('**/api/v1/diagnostics',route=>route.fulfill({json:ordinary}));
 await page.goto('/');await page.getByLabel('Language / Язык').selectOption(lang);
 await expect(page.getByRole('heading',{name:lang==='ru'?'Ближайшие запуски':'Next scheduled runs'})).toBeVisible();
 await expect(page.getByText(lang==='ru'?'По данным диагностики. Подключение к источникам здесь не проверяется.':'Diagnostic snapshot; source connectivity is not tested here.')).toBeVisible();
 await expect(page.getByText(/100/)).toBeVisible();await overflow(page);
 await page.screenshot({path:`test-results/review-overview-ordinary-${lang}-${theme}-${width}.png`,fullPage:true});
});
