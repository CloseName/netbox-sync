import { test, expect } from "./operation-fixture";
import {
  diagnostics,
  run,
  runId,
  staleWarning,
  source,
} from "../tests/fixtures.mjs";
const id = (n: number) =>
  "11111111-1111-4111-8111-" + String(n).padStart(12, "0");
async function mock(page, options: any = {}) {
  const data = options.data ?? diagnostics();
  const rows = options.rows ?? [run()];
  const requests: URL[] = [];
  let fail = !!options.fail;
  await page.route("**/api/v1/**", async (route) => {
    expect(route.request().method()).toBe("GET");
    const url = new URL(route.request().url());
    requests.push(url);
    if (url.pathname === "/api/v1/diagnostics")
      return route.fulfill({
        status: fail ? 503 : 200,
        json: fail ? {} : data,
      });
    if (url.pathname === "/api/v1/runs") {
      if (options.runsFail) return route.fulfill({ status: 503, json: {} });
      const offset = url.searchParams.has("cursor")
        ? rows.findIndex((r) => r.run_id === url.searchParams.get("cursor")) + 1
        : 0;
      const pageRows = rows.slice(offset, offset + 50);
      return route.fulfill({
        json: {
          runs: pageRows,
          next_cursor: pageRows.length === 50 ? pageRows.at(-1).run_id : null,
        },
      });
    }
    if (url.pathname.startsWith("/api/v1/runs/"))
      return route.fulfill({
        status: options.detailFail ? 404 : 200,
        json:
          rows.find((r) => r.run_id === url.pathname.split("/").at(-1)) ??
          run(),
      });
    if (url.pathname.endsWith("/schedule"))
      return route.fulfill({
        json: {
          source_instance: "source-1",
          sync_enabled: true,
          sync_interval_seconds: 600,
          scheduler_state: "WAITING",
          last_scheduled_run_at: null,
          next_expected_at: null,
        },
      });
    if (url.pathname === "/api/v1/sources/source-1")
      return route.fulfill({ json: source() });
    return route.fulfill({ status: 404, json: {} });
  });
  return {
    requests,
    fail: () => {
      fail = true;
    },
  };
}
const labels = {
  SUCCEEDED: "Completed",
  FAILED_BEFORE_WRITE: "Failed before changes",
  BLOCKED: "Blocked by safety checks",
  LOCKED: "Not started — sync busy",
  PARTIALLY_APPLIED: "Partially applied",
  OUTCOME_UNCERTAIN: "Outcome unknown",
  FAILED: "Failed",
  RUNNING: "Recorded as running",
};
for (const [status, label] of Object.entries(labels))
  test("run outcome and null duration: " + status, async ({ page }) => {
    await mock(page, {
      rows: [{ ...run(status), duration_ms: null, finished_at: null }],
    });
    await page.goto("/runs");
    const table = page.getByRole("region", { name: "Run history table" });
    await expect(table).toContainText(label);
    await expect(table).toContainText("Not recorded");
    await expect(table).not.toContainText("objects changed");
    await table.getByRole("link", { name: label, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Run details",
    );
    await expect(
      page.getByText("Completion timestamp not recorded", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Counts describe recorded plan actions, not confirmed applied objects.",
      ),
    ).toBeVisible();
    await page.getByText("Technical details", { exact: true }).click();
    await expect(page.getByText(runId, { exact: true }).last()).toBeVisible();
    await expect(
      page.getByRole("link", { name: "Open source diagnostics" }),
    ).toHaveAttribute("href", "/sources/source-1/diagnostics");
  });
test("cursor traverses 51 rows with server filters and preserves investigation URL", async ({
  page,
}) => {
  const rows = Array.from({ length: 51 }, (_, i) => ({
    ...run(),
    run_id: id(i + 1),
  }));
  const fixture = await mock(page, { rows });
  await page.goto("/runs");
  await expect(page.locator(".run-table tbody tr")).toHaveCount(50);
  await page.getByRole("textbox", { name: "Source ID" }).fill("source-1");
  await page
    .getByRole("button", { name: "Filter source", exact: true })
    .click();
  await page
    .getByRole("combobox", { name: "Provider", exact: true })
    .selectOption("proxmox");
  await page
    .getByRole("combobox", { name: "Outcome", exact: true })
    .selectOption("SUCCEEDED");
  await page.getByRole("combobox", { name: "Trigger", exact: true }).focus();
  await page
    .getByRole("combobox", { name: "Trigger", exact: true })
    .selectOption("manual");
  await expect(
    page.getByRole("combobox", { name: "Trigger", exact: true }),
  ).toBeFocused();
  await expect
    .poll(() =>
      fixture.requests
        .filter((u) => u.pathname === "/api/v1/runs")
        .at(-1)
        ?.searchParams.get("trigger"),
    )
    .toBe("manual");
  await page.getByRole("button", { name: "Older runs" }).click();
  await expect(page.locator(".run-table tbody tr")).toHaveCount(1);
  expect(
    fixture.requests
      .filter((u) => u.pathname === "/api/v1/runs")
      .at(-1)
      ?.searchParams.get("cursor"),
  ).toBe(id(50));
  const url = page.url();
  await page
    .locator(".run-table tbody tr")
    .getByRole("link", { name: "Completed", exact: true })
    .click();
  await page.getByRole("link", { name: "Back to runs" }).click();
  await expect(page).toHaveURL(url);
  await page.getByRole("button", { name: "Newest runs" }).click();
  await expect(page.locator(".run-table tbody tr")).toHaveCount(50);
  await page.goBack();
  await expect(page.locator(".run-table tbody tr")).toHaveCount(1);
});
test("stale evidence is exact, contextual and has no retry sync", async ({
  page,
}) => {
  const d = diagnostics();
  d.overall_status = "DEGRADED";
  d.stale_runs = [staleWarning];
  d.warnings = [staleWarning];
  await mock(page, {
    data: d,
    rows: [run("RUNNING"), { ...run("RUNNING"), run_id: id(2) }],
  });
  await page.goto("/runs");
  await expect(page.locator(".run-table tbody tr").first()).toContainText(
    "Completion unconfirmed",
  );
  await expect(page.locator(".run-table tbody tr").last()).toContainText(
    "Recorded as running",
  );
  await page
    .locator(".run-table")
    .getByRole("link", { name: "Completion unconfirmed", exact: true })
    .click();
  await expect(
    page.getByText(
      "Recorded as RUNNING. No completion was recorded within the expected window.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(
    page.getByText("Age at diagnostic snapshot:", { exact: false }),
  ).toContainText("2 h 46 min 40 s");
  await expect(page.getByRole("button", { name: /retry sync/i })).toHaveCount(
    0,
  );
  await page.getByRole("link", { name: "View system diagnostics" }).click();
  await expect(
    page.getByRole("region", { name: "System assessment" }),
  ).toContainText("Needs attention");
});
test("empty, filtered empty, list failure, detail failure and retry are distinct", async ({
  page,
}) => {
  await mock(page, { rows: [] });
  await page.goto("/runs");
  await expect(page.getByText("No runs have been recorded yet.")).toBeVisible();
  await page.goto("/runs?status=FAILED");
  await expect(page.getByText("No runs match these filters.")).toBeVisible();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .last()
    .click();
  await expect(page).toHaveURL(/\/runs$/);
  await page.unroute("**/api/v1/**");
  await mock(page, { runsFail: true, detailFail: true });
  await page.reload();
  await expect(page.getByRole("alert")).toContainText(
    "History could not be loaded",
  );
  await expect(page.getByText("No runs have been recorded yet.")).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Retry", exact: true }),
  ).toBeVisible();
  await page.goto("/runs/" + runId);
  await expect(page.getByRole("alert")).toContainText(
    "Run could not be loaded",
  );
});
test("query changes never display prior filter results while loading or after failure", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/runs");
  await expect(page.locator(".run-table tbody tr")).toHaveCount(1);
  await page.route("**/api/v1/runs?**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page
    .getByRole("combobox", { name: "Outcome", exact: true })
    .selectOption("FAILED");
  await expect(page.getByRole("alert")).toContainText(
    "History could not be loaded",
  );
  await expect(page.locator(".run-table tbody tr")).toHaveCount(0);
});
test("diagnostic healthy checks disclose actual evidence; unknown is never available", async ({
  page,
}) => {
  const d = diagnostics();
  d.components.scheduler = {
    ...d.components.scheduler,
    status: "UNKNOWN",
    last_seen_at: null,
    last_success_at: null,
    safe_message: "No scheduled runs have been recorded.",
  };
  d.sources[0].status = "UNKNOWN";
  d.sources[0].latest_run = null;
  await mock(page, { data: d });
  await page.goto("/diagnostics");
  const component = page.locator("#component-scheduler");
  await expect(component).toContainText("Not verified");
  await expect(component).toContainText(
    "No scheduled runs have been recorded.",
  );
  await expect(component).not.toContainText("Available");
  await expect(page.locator("#component-apply_worker")).toContainText(
    "connectivity are not tested",
  );
  await component.getByText("Technical details", { exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(component.getByText("Recorded status")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Source diagnostic evidence" }),
  ).toContainText("No runs recorded");
});
test("stale-only degraded keeps aggregate and links to real run and source", async ({
  page,
}) => {
  const d = diagnostics();
  d.overall_status = "DEGRADED";
  d.stale_runs = [staleWarning];
  d.warnings = [staleWarning];
  await mock(page, { data: d });
  await page.goto("/diagnostics");
  await expect(
    page.getByRole("region", { name: "System assessment" }),
  ).toContainText("Needs attention");
  await expect(
    page.getByRole("region", { name: "System assessment" }),
  ).toContainText("Checked components are available");
  await expect(
    page
      .locator(".diagnostic-attention")
      .getByRole("link", { name: "Open run" }),
  ).toHaveAttribute("href", "/runs/" + runId);
  await expect(
    page
      .locator(".diagnostic-attention")
      .getByRole("link", { name: "Source diagnostics" }),
  ).toHaveAttribute("href", "/sources/source-1/diagnostics");
  // A newer successful run stays completed, even with an older stale warning.
  await expect(
    page.getByRole("region", { name: "Source diagnostic evidence" }),
  ).toContainText("Completed");
});
test("unavailable registry hides source assessments and preserves unhealthy aggregate", async ({
  page,
}) => {
  const d = diagnostics();
  d.overall_status = "UNHEALTHY";
  d.components.registry.status = "UNAVAILABLE";
  d.components.registry.safe_code = "REGISTRY_UNAVAILABLE";
  d.components.registry.safe_message = "Source registry is unavailable.";
  await mock(page, { data: d });
  await page.goto("/diagnostics");
  await expect(
    page.getByRole("region", { name: "System assessment" }),
  ).toContainText("Unhealthy");
  await expect(page.locator("#component-registry")).toContainText(
    "Unavailable",
  );
  await expect(
    page.getByText(
      "Source evidence unavailable. Registry and run history checks must both succeed.",
    ),
  ).toBeVisible();
  await expect(page.getByText(/No sources configured/)).toHaveCount(0);
});
test("mixed source attention, delayed schedule and bounded stale sample", async ({
  page,
}) => {
  const d = diagnostics([source(), source(3)]);
  d.overall_status = "DEGRADED";
  d.sources[0].latest_run.status = "OUTCOME_UNCERTAIN";
  d.sources[0].status = "DEGRADED";
  d.sources[1].warnings = ["SCHEDULED_ACTIVITY_DELAYED"];
  d.sources[1].scheduler_state = "DELAYED";
  d.stale_runs = Array.from({ length: 100 }, (_, i) => ({
    ...staleWarning,
    run_id: id(i + 1),
  }));
  d.warnings = [
    ...d.stale_runs,
    {
      ...staleWarning,
      warning_code: "SCHEDULED_ACTIVITY_DELAYED",
      run_id: null,
      source_instance: "source-3",
      age_seconds: null,
      started_at: null,
    },
  ];
  await mock(page, { data: d });
  await page.goto("/diagnostics");
  await expect(
    page.getByText(/The 100 oldest stale runs are shown/),
  ).toBeVisible();
  await expect(page.locator(".diagnostic-attention")).toContainText(
    "Outcome unknown",
  );
  await expect(
    page
      .locator(".diagnostic-attention")
      .getByRole("link", { name: "Open schedule" }),
  ).toHaveAttribute("href", "/sources/source-3/schedule");
});
test("refresh failures retain old diagnostics and explicitly mark data freshness", async ({
  page,
}) => {
  const fixture = await mock(page);
  await page.goto("/diagnostics");
  await expect(page.locator("#component-api")).toBeVisible();
  fixture.fail();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Could not refresh diagnostics. Showing data from",
  );
  await expect(page.getByRole("alert").locator("time")).toHaveAttribute(
    "datetime",
    diagnostics().generated_at,
  );
  await expect(page.locator("#component-api")).toBeVisible();
});
test("source diagnostics uses exact stale links without duplicating component checks", async ({
  page,
}) => {
  const d = diagnostics();
  d.sources[0].warnings = ["STALE_RUNNING"];
  d.sources[0].latest_run.status = "RUNNING";
  d.stale_runs = [staleWarning];
  d.warnings = [staleWarning];
  await mock(page, { data: d });
  await page.goto("/sources/source-1/diagnostics");
  await expect(
    page.getByRole("heading", { name: "Source diagnostics", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(".diagnostic-attention")
      .getByRole("link", { name: "Open run" }),
  ).toHaveAttribute("href", "/runs/" + runId);
  await expect(page.locator("#component-api")).toHaveCount(0);
  await expect(page.locator(".source-panel").last()).toContainText(
    "Completion unconfirmed",
  );
});
for (const width of [1440, 1280, 1024, 768])
  test("UI-4 visual layouts " + width, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    const d = diagnostics();
    d.overall_status = "DEGRADED";
    d.stale_runs = [staleWarning];
    d.warnings = [staleWarning];
    d.sources[0].status = "DEGRADED";
    const rows = Array.from({ length: 51 }, (_, i) => ({
      ...run(i === 0 ? "OUTCOME_UNCERTAIN" : "SUCCEEDED"),
      run_id: i === 0 ? runId : id(i + 1),
    }));
    await mock(page, { data: d, rows });
    for (const [route, name] of [
      ["/runs", "runs"],
      ["/runs/" + runId, "detail"],
      ["/diagnostics", "diagnostics"],
    ]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      if (name === "runs")
        await expect(page.locator(".run-table tbody tr")).toHaveCount(50);
      if (name === "diagnostics")
        await expect(page.locator("#component-api")).toBeVisible();
      if (name === "detail")
        await expect(
          page.getByRole("heading", { name: "Plan actions" }),
        ).toBeVisible();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: "test-results/ui4-" + name + "-" + width + ".png",
        fullPage: true,
      });
    }
  });

for (const width of [1440, 1280, 1024, 768])
  test("UI-4 state gallery " + width, async ({ page }) => {
    await page.setViewportSize({ width, height: 950 });
    const healthy = diagnostics(),
      stale = diagnostics(),
      unavailable = diagnostics(),
      noActivity = diagnostics(),
      mixed = diagnostics([source(), source(3)]);
    stale.overall_status = "DEGRADED";
    stale.stale_runs = [staleWarning];
    stale.warnings = [staleWarning];
    stale.sources[0].warnings = ["STALE_RUNNING"];
    stale.sources[0].status = "DEGRADED";
    unavailable.overall_status = "DEGRADED";
    unavailable.components.apply_worker.status = "UNAVAILABLE";
    unavailable.components.apply_worker.safe_code = "APPLY_WORKER_UNAVAILABLE";
    unavailable.components.apply_worker.safe_message =
      "Apply worker is unavailable.";
    noActivity.components.scheduler.status = "UNKNOWN";
    noActivity.components.scheduler.last_seen_at = null;
    noActivity.components.scheduler.last_success_at = null;
    noActivity.components.scheduler.safe_message =
      "No scheduled runs have been recorded.";
    mixed.overall_status = "DEGRADED";
    mixed.sources[0].latest_run.status = "PARTIALLY_APPLIED";
    mixed.sources[0].status = "DEGRADED";
    mixed.sources[1].warnings = ["SCHEDULED_ACTIVITY_DELAYED"];
    mixed.sources[1].scheduler_state = "DELAYED";
    mixed.warnings = [
      {
        ...staleWarning,
        warning_code: "SCHEDULED_ACTIVITY_DELAYED",
        source_instance: "source-3",
        run_id: null,
        age_seconds: null,
        started_at: null,
      },
    ];
    const scenarios = [
      { name: "one-run", path: "/runs", options: {}, ready: ".run-table" },
      {
        name: "filtered",
        path: "/runs?source_instance=source-1&status=RUNNING",
        options: { rows: [run("RUNNING")], data: stale },
        ready: ".run-table",
      },
      {
        name: "empty",
        path: "/runs",
        options: { rows: [] },
        ready: ".empty-state",
      },
      {
        name: "error",
        path: "/runs",
        options: { runsFail: true },
        ready: "[role=alert]",
      },
      {
        name: "stale-detail",
        path: "/runs/" + runId,
        options: { rows: [run("RUNNING")], data: stale },
        ready: ".evidence-note",
      },
      ...[
        ["healthy", healthy],
        ["stale-only", stale],
        ["worker-unavailable", unavailable],
        ["no-activity", noActivity],
        ["mixed", mixed],
        ["refresh-failed", healthy],
      ].map(([name, data]) => ({
        name,
        path: "/diagnostics",
        options: { data },
        ready: "#component-api",
      })),
    ];
    for (const scenario of scenarios) {
      await page.unroute("**/api/v1/**");
      const fixture = await mock(page, scenario.options);
      await page.goto(scenario.path);
      await expect(page.locator(scenario.ready).first()).toBeVisible();
      if (scenario.name === "refresh-failed") {
        fixture.fail();
        await page
          .getByRole("button", { name: "Refresh", exact: true })
          .click();
        await expect(page.getByRole("alert")).toContainText(
          "Could not refresh",
        );
      }
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page.screenshot({
        path: "test-results/ui4-state-" + scenario.name + "-" + width + ".png",
        fullPage: true,
      });
    }
  });
test("runs refresh failure retains rows and source filters track browser history", async ({
  page,
}) => {
  await mock(page);
  await page.goto("/runs?source_instance=source-1");
  await expect(page.locator(".run-table")).toBeVisible();
  await page.route("**/api/v1/runs?**", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Could not refresh history. Showing data from",
  );
  await expect(page.locator(".run-table")).toBeVisible();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await expect(page.getByRole("textbox", { name: "Source ID" })).toHaveValue(
    "",
  );
  await expect(page).toHaveURL(/\/runs$/);
  await page.goBack();
  await expect(page).toHaveURL(/source_instance=source-1/);
  await expect(page.getByRole("textbox", { name: "Source ID" })).toHaveValue(
    "source-1",
  );
});

test("diagnostics initial failure retries without invented source counts", async ({
  page,
}) => {
  await mock(page, { fail: true });
  await page.goto("/diagnostics");
  await expect(page.getByRole("alert")).toContainText(
    "Diagnostics could not be loaded",
  );
  await expect(
    page.getByRole("region", { name: "System assessment" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("No sources configured.", { exact: false }),
  ).toHaveCount(0);
  await page.unroute("**/api/v1/**");
  await mock(page);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    page.getByRole("region", { name: "System assessment" }),
  ).toContainText("Healthy");
});
test("exact full last page can lead to empty older response without invented totals", async ({
  page,
}) => {
  await mock(page, {
    rows: Array.from({ length: 50 }, (_, i) => ({
      ...run(),
      run_id: id(i + 1),
    })),
  });
  await page.goto("/runs");
  await expect(page.locator(".run-table tbody tr")).toHaveCount(50);
  await page.getByRole("button", { name: "Older runs" }).click();
  await expect(page.getByText("No older runs were returned.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Older runs" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Newest runs" })).toBeVisible();
});
test("unavailable diagnostic history cannot derive stale on a recorded run", async ({
  page,
}) => {
  const d = diagnostics();
  d.components.run_history.status = "UNAVAILABLE";
  d.stale_runs = [staleWarning];
  d.warnings = [staleWarning];
  await mock(page, { data: d, rows: [run("RUNNING")] });
  await page.goto("/runs");
  await expect(page.locator(".run-table")).toContainText("Recorded as running");
  await expect(page.locator(".run-table")).not.toContainText(
    "Completion unconfirmed",
  );
});
