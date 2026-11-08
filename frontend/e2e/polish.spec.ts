import { test, expect, type Page } from "@playwright/test";

async function openDemo(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open public demo", exact: true })
    .click();
  await expect(page.locator(".turn-row").first()).toBeVisible();
}

test("dialogs animate, contain keyboard focus, close with Escape and return focus", async ({
  page,
}, info) => {
  await openDemo(page);
  const settings = page.getByRole("button", { name: "Settings", exact: true });
  await settings.click();
  const dialog = page.getByRole("dialog", { name: "Settings", exact: true });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Close", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(
    await dialog.evaluate((el) => el.contains(document.activeElement)),
  ).toBeTruthy();
  for (let index = 0; index < 18; index++) {
    await page.keyboard.press("Tab");
    expect(
      await dialog.evaluate((el) => el.contains(document.activeElement)),
    ).toBeTruthy();
  }
  await expect(page.locator(".main-shell")).toHaveAttribute("inert", "");
  await page.screenshot({
    path: info.outputPath("settings-glass.png"),
    animations: "disabled",
  });
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(settings).toBeFocused();
  await expect(page.locator(".main-shell")).not.toHaveAttribute("inert", "");
  // A complete close/reopen must not leave a stale exit timer or focus trap.
  await settings.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("tab highlight moves without replacing audio and press feedback cleans itself up", async ({
  page,
}, info) => {
  await openDemo(page);
  const marker = page.locator(".view-tabs .tab-highlight");
  const before = await marker.evaluate((el) => el.getBoundingClientRect().x);
  await page
    .getByRole("button", { name: "Review queue", exact: false })
    .click();
  await expect
    .poll(() => marker.evaluate((el) => el.getBoundingClientRect().x))
    .toBeGreaterThan(before + 100);
  await expect(page.locator(".view-tabs button.active")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.getByRole("button", { name: "Transcript", exact: true }).click();
  await page.getByRole("button", { name: "Start review", exact: true }).click();
  await page.getByRole("button", { name: /^Play this excerpt/ }).click();
  await expect(page.locator(".press-ripple")).toHaveCount(1);
  await expect(page.locator(".press-ripple")).toHaveCount(0);
  const audio = page.locator(".player audio");
  await expect
    .poll(() => audio.evaluate((el: HTMLAudioElement) => el.currentTime))
    .toBeGreaterThan(0);
  await page.getByRole("button", { name: /^Pause excerpt/ }).click();
  await page.getByRole("button", { name: "Assistant", exact: true }).click();
  await expect(page.locator(".player audio")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Review excerpt", exact: true })
    .click();
  await page.screenshot({
    path: info.outputPath("workspace-polished.png"),
    animations: "disabled",
  });
});

test("processing shows project jobs only and completed results open directly", async ({
  page,
}, info) => {
  await openDemo(page);
  const projects = await (await page.request.get("/api/v1/projects")).json();
  const project = projects.find(
    (p: { name: string }) => p.name === "LibriSpeech review demo",
  );
  const records = await (
    await page.request.get(`/api/v1/projects/${project.id}/recordings`)
  ).json();
  const fixture = {
    id: "public-complete",
    recording_id: records[0].id,
    status: "completed",
    stage: "completed",
    progress: 1,
    kind: "process",
    mode: "fast",
    language: "en",
    details: {},
    error: null,
  };
  await page.route("**/api/v1/jobs", (route) =>
    route.fulfill({
      json: [
        fixture,
        { ...fixture, id: "foreign-job", recording_id: "other-project-id" },
      ],
    }),
  );
  await page.getByRole("button", { name: "Processing", exact: true }).click();
  await expect(page.locator(".job-card")).toHaveCount(1);
  await expect(page.locator(".processing-overview")).toContainText(
    "Draft ready",
  );
  await page.screenshot({
    path: info.outputPath("processing-polished.png"),
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "Open transcript", exact: false })
    .click();
  await expect(page.locator(".turn-row").first()).toBeVisible();
});

test("reduced motion disables decorative motion, ripple and animated overlays", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openDemo(page);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(
    await page
      .locator(".modal")
      .evaluate((el) => getComputedStyle(el).animationName),
  ).toBe("none");
  expect(
    await page
      .locator(".tab-highlight")
      .evaluate((el) => getComputedStyle(el).transitionDuration),
  ).toBe("0s");
  await expect(page.locator(".press-ripple")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("filters dismiss cleanly and a new-project dialog restores its trigger", async ({
  page,
}) => {
  await openDemo(page);
  const filters = page.locator(".transcript-filters > summary");
  await filters.click();
  await expect(page.getByLabel("All speakers", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".transcript-filters")).not.toHaveAttribute(
    "open",
    "",
  );
  await expect(filters).toBeFocused();
  await filters.click();
  await page.locator(".recording-heading h1").click();
  await expect(page.locator(".transcript-filters")).not.toHaveAttribute(
    "open",
    "",
  );
  const create = page.getByRole("button", { name: "New project", exact: true });
  await create.click();
  await expect(page.getByLabel("Project name", { exact: true })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(create).toBeFocused();
});
