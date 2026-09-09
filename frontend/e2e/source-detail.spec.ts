import { test, expect } from "./operation-fixture";
import { source, diagnostics, run, runId } from "../tests/fixtures.mjs";
async function fixture(page, options: any = {}) {
  const sources = [source(), { ...source(2), enabled: true }],
    data = diagnostics(sources);
  if (options.failed) data.sources[0].latest_run.status = "FAILED_BEFORE_WRITE";
  if (options.empty) {
    data.sources[0].latest_run = null;
    data.sources[0].latest_success_at = null;
  }
  if (options.warning) {
    data.sources[0].warnings = ["SCHEDULED_ACTIVITY_DELAYED"];
    data.sources[0].warning_count = 1;
    data.sources[0].status = "DEGRADED";
  }
  const schedules = Object.fromEntries(
    sources.map((s) => [
      s.source_instance,
      {
        source_instance: s.source_instance,
        sync_enabled: !options.off,
        sync_interval_seconds: options.interval ?? 600,
        scheduler_state: options.off ? "DISABLED" : "WAITING",
        last_scheduled_run_at: null,
        next_expected_at: null,
      },
    ]),
  );
  const calls: any[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname;
    calls.push({
      path,
      method: request.method(),
      query: url.searchParams,
      body: request.postDataJSON(),
    });
    if (path === "/api/v1/diagnostics")
      return route.fulfill({
        status: options.unavailable ? 503 : 200,
        json: options.unavailable ? {} : data,
      });
    if (path === "/api/v1/sources") return route.fulfill({ json: { sources } });
    if (path === "/api/v1/runs")
      return route.fulfill({
        json: {
          runs: [
            {
              ...run(),
              source_instance:
                url.searchParams.get("source_instance") ?? "source-1",
            },
          ],
          next_cursor: null,
        },
      });
    if (path === "/api/v1/runs/" + runId) return route.fulfill({ json: run() });
    const id = path.split("/")[4];
    if (path.endsWith("/schedule") && schedules[id]) {
      if (request.method() === "PATCH")
        Object.assign(schedules[id], {
          sync_enabled: request.postDataJSON().sync_enabled,
          sync_interval_seconds: request.postDataJSON().sync_interval_seconds,
        });
      return route.fulfill({ json: schedules[id] });
    }
    const found = sources.find(
      (s) => path === "/api/v1/sources/" + s.source_instance,
    );
    return route.fulfill({ status: found ? 200 : 404, json: found ?? {} });
  });
  return { calls, schedules, data };
}
const section = (page, name) =>
  page
    .getByRole("navigation", { name: "Source sections" })
    .getByRole("link", { name, exact: true });
for (const [suffix, title] of [
  ["", "Source overview"],
  ["sync", "Sync"],
  ["runs", "Source runs"],
  ["schedule", "Schedule"],
  ["diagnostics", "Source diagnostics"],
  ["configuration", "Configuration"],
]) {
  test(
    "direct source route and refresh: " + (suffix || "overview"),
    async ({ page }) => {
      await fixture(page);
      await page.goto("/sources/source-1" + (suffix ? "/" + suffix : ""));
      await expect(
        page.getByRole("heading", { name: title, exact: true }),
      ).toBeVisible();
      await expect(
        section(
          page,
          suffix ? suffix[0].toUpperCase() + suffix.slice(1) : "Overview",
        ),
      ).toHaveAttribute("aria-current", "page");
      await expect(
        page.getByRole("navigation", { name: "Breadcrumb" }),
      ).toContainText("Source 001");
      await page.reload();
      await expect(
        page.getByRole("heading", { name: title, exact: true }),
      ).toBeVisible();
      await page.screenshot({
        path: "test-results/ui2-" + (suffix || "overview") + ".png",
        fullPage: true,
      });
    },
  );
}
test("tabs use links and preserve shared data, edits and Back/Forward", async ({
  page,
}) => {
  const { calls } = await fixture(page);
  await page.goto("/sources/source-1");
  await expect(page.getByRole("heading", { name: "Source 001" })).toBeVisible();
  const count = calls.filter(
    (c) => c.path === "/api/v1/sources/source-1",
  ).length;
  await section(page, "Schedule").focus();
  await page.keyboard.press("Enter");
  await page
    .getByRole("button", { name: "Edit schedule", exact: true })
    .click();
  await page.getByLabel("Frequency", { exact: true }).selectOption("custom");
  await page.getByLabel("Custom interval").fill("73");
  await section(page, "Configuration").click();
  await page.goBack();
  await expect(page.getByLabel("Custom interval")).toHaveValue("73");
  await page.goForward();
  await expect(page).toHaveURL(/configuration$/);
  expect(
    calls.filter((c) => c.path === "/api/v1/sources/source-1").length,
  ).toBe(count);
  await expect(page.getByRole("tab")).toHaveCount(0);
});
test("schedule exact value, pending duplicate protection and success", async ({
  page,
}) => {
  const { calls } = await fixture(page, { interval: 601 });
  let release: any, submitted: any;
  await page.route("**/api/v1/sources/source-1/schedule", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    submitted = route.request().postDataJSON();
    await new Promise((resolve) => {
      release = resolve;
    });
    await route.fulfill({
      json: {
        source_instance: "source-1",
        ...submitted,
        scheduler_state: "WAITING",
        last_scheduled_run_at: null,
        next_expected_at: null,
      },
    });
  });
  await page.goto("/sources/source-1/schedule");
  await expect(
    page.getByText("Every 10 min 1 s", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Edit schedule", exact: true })
    .click();
  await expect(page.getByLabel("Frequency", { exact: true })).toHaveValue(
    "custom",
  );
  await expect(page.getByLabel("Custom interval")).toHaveValue("601");
  await expect(page.getByLabel("Unit", { exact: true })).toHaveValue("seconds");
  await page.getByLabel("Custom interval").fill("2.5");
  await page.getByLabel("Unit", { exact: true }).selectOption("hours");
  await page
    .getByRole("checkbox", { name: "Automatic sync", exact: true })
    .uncheck();
  await expect(
    page.getByText(
      "Future automatic runs are disabled. A run that has already started is not cancelled.",
    ),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/ui2-schedule-edit.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByRole("button", { name: "Saving…" })).toBeDisabled();
  await expect(page.getByLabel("Custom interval")).toHaveValue("2.5");
  expect(submitted).toEqual({
    sync_enabled: false,
    sync_interval_seconds: 9000,
    expected_sync_enabled: true,
    expected_sync_interval_seconds: 601,
  });
  release();
  await expect(
    page.getByRole("status").filter({ hasText: "Saved" }),
  ).toBeVisible();
  await expect(
    page.getByText("Every 2 h 30 min", { exact: true }),
  ).toBeVisible();
});
test("conflict requires explicit reload; failed reload keeps save blocked", async ({
  page,
}) => {
  const { schedules } = await fixture(page);
  let phase = "conflict";
  await page.route("**/api/v1/sources/source-1/schedule", (route) => {
    if (route.request().method() === "PATCH")
      return route.fulfill({
        status: 409,
        json: { error: { code: "SCHEDULE_CONFLICT", message: "SECRET" } },
      });
    if (phase === "reload-failure")
      return route.fulfill({ status: 503, json: {} });
    return route.fallback();
  });
  await page.goto("/sources/source-1/schedule");
  await page
    .getByRole("button", { name: "Edit schedule", exact: true })
    .click();
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "This schedule changed since you opened it. Reload the latest value before saving again.",
  );
  await expect(
    page.getByRole("button", { name: "Save schedule" }),
  ).toBeDisabled();
  phase = "reload-failure";
  await page.getByRole("button", { name: "Reload latest schedule" }).click();
  await expect(
    page.getByText(
      "Latest schedule could not be loaded. Reload before saving again.",
    ),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Save schedule" }),
  ).toBeDisabled();
  phase = "reload-success";
  schedules["source-1"].sync_interval_seconds = 7200;
  await page.getByRole("button", { name: "Reload latest schedule" }).click();
  await expect(page.getByLabel("Frequency", { exact: true })).toHaveValue(
    "7200",
  );
  await expect(
    page.getByRole("button", { name: "Save schedule" }),
  ).toBeEnabled();
});
test("backend error preserves fields, hides raw details and permits deliberate retry", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/sources/source-1/schedule", (route) =>
    route.request().method() === "PATCH"
      ? route.fulfill({
          status: 503,
          json: {
            error: { code: "CONTROL_WORKER_UNAVAILABLE", message: "SECRET" },
          },
        })
      : route.fallback(),
  );
  await page.goto("/sources/source-1/schedule");
  await page
    .getByRole("button", { name: "Edit schedule", exact: true })
    .click();
  await page.getByLabel("Frequency", { exact: true }).selectOption("7200");
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Scheduling control is unavailable.",
  );
  await expect(page.getByLabel("Frequency", { exact: true })).toHaveValue(
    "7200",
  );
  await expect(
    page.getByRole("button", { name: "Save schedule" }),
  ).toBeEnabled();
  await expect(page.getByText("SECRET")).toHaveCount(0);
});
for (const value of [30, 86401, 2147483647])
  test("out-of-update-range stored interval " + value, async ({ page }) => {
    await fixture(page, { interval: value });
    await page.goto("/sources/source-1/schedule");
    await page
      .getByRole("button", { name: "Edit schedule", exact: true })
      .click();
    await expect(page.getByLabel("Custom interval")).toHaveValue(String(value));
    await expect(page.getByLabel("Unit", { exact: true })).toHaveValue(
      "seconds",
    );
    await expect(
      page.getByRole("button", { name: "Save schedule" }),
    ).toBeDisabled();
    await expect(
      page.getByText(/Registration accepts a wider range/),
    ).toBeVisible();
    await page.screenshot({
      path: "test-results/ui2-unusual-" + value + ".png",
      fullPage: true,
    });
  });
test("schedule save A finishing on B cannot replace B state", async ({
  page,
}) => {
  await fixture(page);
  let release: any;
  await page.route("**/api/v1/sources/source-1/schedule", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    await new Promise((resolve) => {
      release = resolve;
    });
    await route.fulfill({
      json: {
        source_instance: "source-1",
        sync_enabled: false,
        sync_interval_seconds: 7200,
        scheduler_state: "DISABLED",
        last_scheduled_run_at: null,
        next_expected_at: null,
      },
    });
  });
  await page.goto("/sources/source-1/schedule");
  await page
    .getByRole("button", { name: "Edit schedule", exact: true })
    .click();
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByRole("button", { name: "Saving…" })).toBeDisabled();
  await page.getByRole("link", { name: "Back to sources" }).click();
  await page.getByRole("link", { name: "Source 002", exact: true }).click();
  await section(page, "Schedule").click();
  await expect(page).toHaveURL(/source-2\/schedule$/);
  release();
  await expect(page.getByRole("heading", { name: "Source 002" })).toBeVisible();
  await expect(
    page.locator(".schedule-panel").getByText("Every 10 min", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Saved", { exact: true })).toHaveCount(0);
});
test("discovery persists across tabs", async ({ page }) => {
  await fixture(page);
  let release: any;
  await page.route("**/api/v1/sources/source-1/operations/discovery", async (route) => {
    await new Promise((resolve) => {
      release = resolve;
    });
    await route.fulfill({
      json: {
        source_instance: "source-1",
        source_type: "proxmox",
        site_slug: "dc1",
        cluster_name: "Cluster 1",
        items: [],
      },
    });
  });
  await page.goto("/sources/source-1/sync");
  await page
    .getByRole("button", { name: "Run discovery", exact: true })
    .click();
  await expect(page.getByText(/Run discovery.*Operation in progress/)).toBeVisible();
  await section(page, "Overview").click();
  await expect(section(page, "Overview")).toHaveAttribute(
    "aria-current",
    "page",
  );
  release();
  await section(page, "Sync").click();
  await expect(
    page.getByRole("combobox", { name: /^Classification/ }),
  ).toBeVisible();
  await section(page, "Schedule").click();
  await section(page, "Sync").click();
  await expect(
    page.getByRole("combobox", { name: /^Classification/ }),
  ).toBeVisible();
});
test("source runs uses the API filter and global detail", async ({ page }) => {
  const { calls } = await fixture(page);
  await page.goto("/sources/source-2/runs");
  await expect(page.getByRole("table")).toContainText("create: 1");
  expect(
    calls.find((c) => c.path === "/api/v1/runs").query.get("source_instance"),
  ).toBe("source-2");
  await page.getByRole("table").getByRole("link").click();
  await expect(page).toHaveURL(new RegExp("/runs/" + runId + "$"));
});
test("not found differs from temporary unavailability and retries", async ({
  page,
}) => {
  await fixture(page);
  await page.goto("/sources/missing/schedule");
  await expect(
    page.getByRole("heading", { name: "Source not found", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/ui2-not-found.png",
    fullPage: true,
  });
  let fail = true;
  await page.route("**/api/v1/sources/source-1", (route) =>
    fail ? route.fulfill({ status: 503, json: {} }) : route.fallback(),
  );
  await page.goto("/sources/source-1/configuration");
  await expect(
    page.getByRole("heading", { name: "Source unavailable", exact: true }),
  ).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Source 001", exact: true }),
  ).toBeVisible();
  await expect(page).toHaveURL(/configuration$/);
});
test("configuration, automatic sync and last outcome remain independent", async ({
  page,
}) => {
  await fixture(page, { off: true, failed: true });
  await page.goto("/sources/source-1");
  await expect(page.locator(".source-header-signals")).toContainText("Enabled");
  await expect(page.locator(".source-header-signals")).toContainText("Off");
  await expect(page.locator(".source-header-signals")).toContainText(
    "Failed before changes",
  );
  await expect(page.locator(".source-panels")).toContainText("Healthy");
  await page.screenshot({
    path: "test-results/ui2-schedule-off.png",
    fullPage: true,
  });
});
test("unavailable evidence and no last run never imply success", async ({
  page,
}) => {
  await fixture(page, { unavailable: true });
  await page.goto("/sources/source-1");
  await expect(page.locator(".source-header-signals")).toContainText(
    "Unavailable",
  );
  await expect(page.locator(".source-workspace")).not.toContainText("Healthy");
  await page.unrouteAll();
  await fixture(page, { empty: true });
  await page.reload();
  await expect(page.locator(".source-header-signals")).toContainText(
    "No run recorded",
  );
  await expect(page.locator(".source-header-signals")).not.toContainText(
    "Completed",
  );
});
for (const width of [1440, 1280, 1024, 768])
  test("source responsive " + width, async ({ page }) => {
    await fixture(page, { warning: true });
    await page.setViewportSize({ width, height: 900 });
    for (const suffix of ["", "schedule", "configuration"]) {
      await page.goto("/sources/source-1" + (suffix ? "/" + suffix : ""));
      await expect(
        page.getByRole("heading", { name: "Source 001", exact: true }),
      ).toBeVisible();
      if (suffix === "schedule")
        await page
          .getByRole("button", { name: "Edit schedule", exact: true })
          .click();
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBeTruthy();
      await page.screenshot({
        path:
          "test-results/ui2-" + (suffix || "warning") + "-" + width + ".png",
        fullPage: true,
      });
    }
  });

test("Build plan needs no discovery, retains result and confirmation semantics across tabs", async ({
  page,
}) => {
  await fixture(page);
  const digest = "a".repeat(64);
  await page.route("**/api/v1/sources/source-1/operations/plan", (route) =>
    route.fulfill({
      json: {
        source_instance: "source-1",
        source_type: "proxmox",
        source_fingerprint: "a",
        target_fingerprint: "b",
        provider_fingerprint: "c",
        netbox_fingerprint: "d",
        schema_version: 1,
        planner_version: "web-5a-1",
        apply_allowed: true,
        digest,
        items: [],
      },
    }),
  );
  await page.route("**/api/v1/sources/source-1/sync-confirmations", (route) => {
    expect(route.request().postDataJSON()).toEqual({
      plan_digest: digest,
      confirmed: true,
      operation_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
    });
    return route.fulfill({ json: { confirmation_token: "b".repeat(64) } });
  });
  await page.route("**/api/v1/sources/source-1/sync", (route) =>
    route.fulfill({ json: { status: "SUCCEEDED", plan_digest: digest } }),
  );
  await page.goto("/sources/source-1/sync");
  await page.getByRole("button", { name: "Build plan", exact: true }).click();
  await expect(page.getByText("Plan ready for review.")).toBeVisible();
  await section(page, "Overview").click();
  await expect(section(page, "Overview")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await section(page, "Sync").click();
  await expect(
    page.getByRole("button", { name: "Review and confirm sync", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Review and confirm sync", exact: true }).click();
  await page.getByRole("button", { name: "Sync to NetBox", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Sync completed", exact: true }),
  ).toBeVisible();
  await section(page, "Schedule").click();
  await expect(section(page, "Schedule")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await section(page, "Sync").click();
  await expect(
    page.getByRole("heading", { name: "Sync completed", exact: true }),
  ).toBeVisible();
});
test("late plan for A cannot appear on B", async ({ page }) => {
  await fixture(page);
  let release: any;
  await page.route("**/api/v1/sources/source-1/operations/plan", async (route) => {
    await new Promise((resolve) => {
      release = resolve;
    });
    await route.fulfill({
      json: {
        source_instance: "source-1",
        source_type: "proxmox",
        source_fingerprint: "a",
        target_fingerprint: "b",
        provider_fingerprint: "c",
        netbox_fingerprint: "d",
        schema_version: 1,
        planner_version: "web-5a-1",
        apply_allowed: true,
        digest: "a".repeat(64),
        items: [],
      },
    });
  });
  await page.goto("/sources/source-1/sync");
  await page.getByRole("button", { name: "Build plan", exact: true }).click();
  await expect(page.getByText(/Build plan.*Operation in progress/)).toBeVisible();
  await page.getByRole("link", { name: "Back to sources" }).click();
  await page.getByRole("link", { name: "Source 002", exact: true }).click();
  await section(page, "Sync").click();
  await expect(page).toHaveURL(/source-2\/sync$/);
  release();
  await expect(
    page.getByRole("heading", { name: "Sync", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Plan ready for review.")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Review and confirm sync", exact: true }),
  ).toHaveCount(0);
});

test("enable automatic sync with exact custom minutes and preserve expectations", async ({
  page,
}) => {
  const { calls } = await fixture(page, { off: true, interval: 601 });
  await page.goto("/sources/source-1/schedule");
  await page
    .getByRole("button", { name: "Edit schedule", exact: true })
    .click();
  await page
    .getByRole("checkbox", { name: "Automatic sync", exact: true })
    .check();
  await expect(
    page.getByText(
      "After saving, this source can be picked up by the scheduler on a future scheduler cycle.",
    ),
  ).toBeVisible();
  await page.getByLabel("Custom interval").fill("1.15");
  await page.getByLabel("Unit", { exact: true }).selectOption("minutes");
  await page.getByRole("button", { name: "Save schedule" }).click();
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  expect(calls.filter((c) => c.method === "PATCH").map((c) => c.body)).toEqual([
    {
      sync_enabled: true,
      sync_interval_seconds: 69,
      expected_sync_enabled: false,
      expected_sync_interval_seconds: 601,
    },
  ]);
});
test("late source configuration response never replaces a different route identity", async ({
  page,
}) => {
  await fixture(page);
  let release: any;
  await page.route("**/api/v1/sources/source-1", async (route) => {
    await new Promise((resolve) => {
      release = resolve;
    });
    await route.fulfill({ json: source() });
  });
  await page.goto("/sources/source-1");
  await expect(page.getByText(/Loading source configuration/)).toBeVisible();
  await page.getByRole("link", { name: "Back to sources" }).click();
  await page.getByRole("link", { name: "Source 002", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Source 002", exact: true }),
  ).toBeVisible();
  release();
  await expect(
    page.getByRole("heading", { name: "Source 002", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Source 001", exact: true }),
  ).toHaveCount(0);
});
test("scheduled outcome and expected time are evidence, not a guaranteed start", async ({
  page,
}) => {
  const { schedules, data } = await fixture(page);
  const started = new Date(Date.now() - 600000).toISOString(),
    next = new Date(Date.now() + 120000).toISOString();
  data.sources[0].latest_scheduled_run = {
    run_id: runId,
    trigger: "scheduled",
    status: "FAILED_BEFORE_WRITE",
    started_at: started,
    finished_at: started,
  };
  schedules["source-1"].last_scheduled_run_at = started;
  schedules["source-1"].next_expected_at = next;
  await page.goto("/sources/source-1/schedule");
  await expect(page.locator(".schedule-panel")).toContainText(
    "Failed before changes",
  );
  await expect(
    page.locator(".schedule-panel time[datetime='" + next + "']"),
  ).toHaveAttribute("title", /.+/);
  await expect(page.getByText(/not a guaranteed start/)).toBeVisible();
  await page.screenshot({
    path: "test-results/ui2-scheduled-evidence.png",
    fullPage: true,
  });
});
