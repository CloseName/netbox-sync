import { test, expect } from "./operation-fixture";
import {
  source,
  diagnostics,
  run,
  runId,
  staleWarning,
} from "../tests/fixtures.mjs";
async function fixture(page, count = 1, options = {}) {
  const sources = Array.from({ length: count }, (_, i) => source(i + 1)),
    data = diagnostics(sources);
  if (options.stale) {
    data.overall_status = "DEGRADED";
    data.sources[0].status = "DEGRADED";
    data.sources[0].warnings = ["STALE_RUNNING"];
    data.sources[0].warning_count = 1;
    data.stale_runs = [staleWarning];
    data.warnings = [staleWarning];
  }
  if (options.unknown) {
    data.sources[0].status = "UNKNOWN";
    data.sources[0].latest_run = null;
  }
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname;
    if (route.request().method() !== "GET")
      throw new Error("Unexpected write in UI fixture");
    if (path === "/api/v1/diagnostics" && options.unavailable)
      return route.fulfill({ status: 503, json: {} });
    const body =
      path === "/api/v1/sources"
        ? { sources }
        : path === "/api/v1/diagnostics"
          ? data
          : path === "/api/v1/runs"
            ? { runs: [run()], next_cursor: null }
            : path.startsWith("/api/v1/runs/")
              ? run()
              : path.endsWith("/schedule")
                ? {
                    source_instance: path.split("/")[4],
                    sync_enabled: false,
                    sync_interval_seconds: 600,
                    scheduler_state: "DISABLED",
                    last_scheduled_run_at: null,
                    next_expected_at: null,
                  }
                : sources.find(
                    (s) => path === "/api/v1/sources/" + s.source_instance,
                  );
    return route.fulfill({ status: body ? 200 : 404, json: body ?? {} });
  });
}
test("direct routes, active navigation, Back/Forward and refresh", async ({
  page,
}) => {
  await fixture(page, 55);
  await page.goto("/sources?provider=proxmox&size=25&page=2");
  await expect(
    page.getByRole("heading", { name: "Sources", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .getByRole("navigation", { name: "Main navigation" })
      .getByRole("link", { name: "Sources" }),
  ).toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: "Source 051", exact: true }).click();
  await expect(page).toHaveURL(/sources\/source-51$/);
  await expect(page.getByRole("heading", { name: "Source 051" })).toBeVisible();
  await page.screenshot({
    path: "test-results/source-detail.png",
    fullPage: true,
  });
  await page.reload();
  await expect(
    page.getByText("source-51", { exact: true }).last(),
  ).toBeVisible();
  await page.getByRole("link", { name: "Back to sources" }).click();
  await expect(page).toHaveURL(/provider=proxmox/);
  await page.goBack();
  await expect(page).toHaveURL(/source-51$/);
  await page.goForward();
  await expect(page).toHaveURL(/provider=proxmox/);
  await page.goto("/runs/" + runId);
  await expect(
    page.getByRole("heading", { level: 1, name: "Run details" }),
  ).toBeVisible();
  await page.reload();
  await page.getByText("Technical details", { exact: true }).click();
  await expect(page.getByText("web/manual")).toBeVisible();
  await page.screenshot({
    path: "test-results/run-detail.png",
    fullPage: true,
  });
  await page.goto("/sources/add");
  await expect(
    page.getByRole("heading", { level: 1, name: "Add source" }),
  ).toBeVisible();
  await expect(page.getByLabel("Hostname or IPv4 address")).toBeVisible();
  await page.screenshot({
    path: "test-results/add-source.png",
    fullPage: true,
  });
});
test("sources filters, pagination, no results, schedule off vs disabled", async ({
  page,
}) => {
  await fixture(page, 55);
  await page.goto("/sources");
  await expect(page.getByText("1–25 of 55")).toBeVisible();
  await expect(
    page.getByRole("row").filter({ hasText: "Source 002" }),
  ).toContainText("Source disabled");
  await expect(
    page.getByRole("row").filter({ hasText: "Source 003" }),
  ).toContainText("Automatic sync off");
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByText("26–50 of 55")).toBeVisible();
  await page.getByLabel("Search sources").fill("absent");
  await expect(page.getByText("No sources match these filters.")).toBeVisible();
  await page.screenshot({
    path: "test-results/filtered-empty.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .first()
    .click();
  await page.getByLabel("Provider", { exact: true }).selectOption("esxi");
  await expect(page.getByText("1–25 of 27")).toBeVisible();
});
test("overview healthy, unknown, stale and partial error preserve epistemic boundaries", async ({
  page,
}) => {
  await fixture(page, 1, { stale: true, unknown: true });
  await page.goto("/");
  await expect(
    page.getByText("Historical run records have unconfirmed completion."),
  ).toBeVisible();
  await expect(page.getByText("Not verified: 1")).toBeVisible();
  await expect(
    page.getByText("Completion unconfirmed: 1 returned run records"),
  ).toBeVisible();
  await page.route("**/api/v1/diagnostics", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Showing data from");
  await expect(page.getByText("1 registered")).toBeVisible();
});
test("diagnostics unavailable preserves sources and never labels them healthy", async ({
  page,
}) => {
  await fixture(page, 1, { unavailable: true });
  await page.goto("/sources");
  await expect(
    page.getByRole("link", { name: "Source 001", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Status unavailable", { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("table")).not.toContainText("Healthy");
  await page.screenshot({
    path: "test-results/diagnostics-unavailable.png",
    fullPage: true,
  });
});
test("empty states and keyboard landmarks", async ({ page }) => {
  await fixture(page, 0);
  await page.goto("/sources");
  await expect(
    page.getByText("No sources have been registered."),
  ).toBeVisible();
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toBeVisible();
});
for (const width of [1440, 1280, 1024, 768])
  test("layout at " + width, async ({ page }) => {
    await fixture(page, 55);
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/sources");
    await expect(
      page.getByRole("link", { name: "Source 001", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    if (width === 768) {
      await page
        .getByRole("button", { name: "Navigation", exact: true })
        .click();
      await expect(
        page.getByRole("navigation", { name: "Main navigation" }),
      ).toBeVisible();
    }
    await page.screenshot({
      path: "test-results/sources-" + width + ".png",
      fullPage: true,
    });
    await page.goto("/");
    await expect(page.getByText("55 registered")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
    await page.screenshot({
      path: "test-results/overview-" + width + ".png",
      fullPage: true,
    });
  });

test("one source and successful overview", async ({ page }) => {
  await fixture(page);
  await page.goto("/sources");
  await expect(page.getByText("1–1 of 1")).toBeVisible();
  await page.screenshot({
    path: "test-results/source-one.png",
    fullPage: true,
  });
  await page.goto("/");
  await expect(page.getByText("Healthy: 1")).toBeVisible();
});
test("source route remount isolates late discovery results", async ({
  page,
}) => {
  await fixture(page, 2);
  await page.goto("/sources/source-1/sync");
  let finish;
  await page.route(
    "**/api/v1/sources/source-1/operations/discovery",
    (route) =>
      new Promise((resolve) => {
        finish = async () => {
          await route.fulfill({
            json: {
              source_instance: "source-1",
              source_type: "proxmox",
              site_slug: "dc1",
              cluster_name: "Cluster 1",
              items: [],
            },
          });
          resolve();
        };
      }),
  );
  await page
    .getByRole("button", { name: "Run discovery", exact: true })
    .click();
  await expect(page.getByText(/Discovering source/)).toBeVisible();
  await page.getByRole("link", { name: "Back to sources" }).click();
  await page.getByRole("link", { name: "Source 002", exact: true }).click();
  await finish();
  await expect(page.getByRole("heading", { name: "Source 002" })).toBeVisible();
  await expect(
    page.getByText("source-2", { exact: true }).last(),
  ).toBeVisible();
  await expect(page.getByLabel("Classification", { exact: true })).toHaveCount(
    0,
  );
});

test("loading and empty run history do not flash zero metrics", async ({
  page,
}) => {
  await fixture(page, 1);
  let release;
  await page.route(
    "**/api/v1/sources",
    (route) =>
      new Promise((resolve) => {
        release = async () => {
          await route.fulfill({ json: { sources: [source()] } });
          resolve();
        };
      }),
  );
  await page.route("**/api/v1/runs?*", (route) =>
    route.fulfill({ json: { runs: [], next_cursor: null } }),
  );
  await page.goto("/");
  await expect(
    page.locator(".summary-panels > section").first().getByRole("status"),
  ).toBeVisible();
  await expect(page.getByText("0 registered")).toHaveCount(0);
  await release();
  await expect(page.getByText("1 registered")).toBeVisible();
  await expect(page.getByText("No runs have been recorded yet.")).toBeVisible();
});
test("history failure leaves independent overview sections available", async ({
  page,
}) => {
  await fixture(page);
  await page.route("**/api/v1/runs?*", (route) =>
    route.fulfill({ status: 503, json: {} }),
  );
  await page.goto("/");
  await expect(page.getByText("1 registered")).toBeVisible();
  await expect(page.getByText("Recent activity unavailable.")).toBeVisible();
  await expect(page.getByRole("alert")).toContainText(
    "Run history unavailable",
  );
});
test("skip link and collapsed navigation are keyboard accessible", async ({
  page,
}) => {
  await fixture(page);
  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/");
  await page.locator("body").click({ position: { x: 760, y: 1 } });
  await page.keyboard.press("Control+Home");
  await page.getByRole("link", { name: "Skip to content" }).focus();
  await expect(
    page.getByRole("link", { name: "Skip to content" }),
  ).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page.locator("#content")).toBeFocused();
  await page.getByRole("button", { name: "Navigation", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("button", { name: "Navigation", exact: true }),
  ).toHaveAttribute("aria-expanded", "true");
});
