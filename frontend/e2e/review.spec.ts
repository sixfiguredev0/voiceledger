import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs/promises";

async function demo(page: Page) {
  await page.goto("/");
  if (
    !(await page
      .getByRole("button", { name: "Open public demo", exact: true })
      .isVisible())
  )
    await page
      .getByRole("button", { name: "Choose a recording", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Open public demo", exact: true })
    .click();
  await expect(page.locator(".turn-row")).toHaveCount(4);
  await expect(page.getByText("PUBLIC DEMO", { exact: true })).toBeVisible();
  await expect(page.locator(".waveform canvas").first()).toBeVisible();
}

test("confirmed names persist through reload and can be undone", async ({
  page,
}, testInfo) => {
  await demo(page);
  await page.locator(".turn-row").nth(2).click();
  await page.getByText("Name assignment options", { exact: true }).click();
  await page
    .getByLabel("Choose a registered person")
    .selectOption({ label: "Reader C" });
  await page
    .getByRole("button", { name: "Preview name assignment", exact: true })
    .click();
  await expect(
    page.getByText("Correction preview", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Apply correction", exact: true })
    .click();
  await expect(page.locator(".turn-row").nth(2)).toContainText("Reader C");
  await page.reload();
  await expect(page.locator(".turn-row").nth(2)).toContainText("Reader C");
  await page.locator(".turn-row").nth(2).click();
  await page.getByRole("button", { name: "Undo", exact: true }).first().click();
  await expect(page.locator(".turn-row").nth(2)).toContainText("Voice 03");
  await page.locator(".panel-scroll").evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({
    path: testInfo.outputPath("desktop-demo.png"),
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
});

test("Bulgarian menus and all processing modes are available", async ({
  page,
}) => {
  await demo(page);
  await page.getByLabel("Interface language").selectOption("bg");
  await expect(
    page.getByRole("button", { name: "Добави аудио", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Настройки", exact: true }).click();
  const dialog = page.getByRole("dialog");
  for (const label of ["Бърза чернова", "Балансиран", "Точност"]) {
    await dialog
      .locator(".mode-cards > button")
      .filter({ hasText: label })
      .click();
    await expect(dialog.locator(".mode-cards > button.selected")).toContainText(
      label,
    );
  }
  await dialog.getByRole("button", { name: "Затвори", exact: true }).click();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Добави аудио", exact: true }),
  ).toBeVisible();
});

test("a recording link opens the intended audio and review clips play", async ({
  page,
}) => {
  await demo(page);
  const projects = await (await page.request.get("/api/v1/projects")).json();
  const project = projects.find(
    (p: { name: string }) => p.name === "LibriSpeech review demo",
  );
  const recordings = await (
    await page.request.get(`/api/v1/projects/${project.id}/recordings`)
  ).json();
  await page.goto(`/?project=${project.id}&recording=${recordings[1].id}`);
  await expect(
    page.getByRole("heading", { name: "session-2", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect
    .poll(() =>
      page
        .locator(".player audio")
        .evaluate((audio: HTMLAudioElement) => audio.currentTime),
    )
    .toBeGreaterThan(0);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await page.locator(".turn-row").first().click();
  await page.getByRole("button", { name: /^Play this excerpt/ }).click();
  await expect
    .poll(() =>
      page
        .locator(".player audio")
        .evaluate((audio: HTMLAudioElement) => audio.currentTime),
    )
    .toBeGreaterThan(0);
});

test("combined export preserves recording boundaries and excludes private paths", async ({
  page,
}) => {
  await demo(page);
  await page.getByRole("button", { name: "Export", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("combobox", { name: "Recordings", exact: true })
    .selectOption("all");
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  const downloading = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download export", exact: true })
    .click();
  const file = await downloading;
  const data = JSON.parse(await fs.readFile((await file.path())!, "utf8"));
  expect(data.recordings).toHaveLength(2);
  expect(data.recordings[0].filename).toBe("session-1.flac");
  expect(JSON.stringify(data)).not.toContain("original_path");
  expect(JSON.stringify(data)).not.toContain("embedding");
});

test("large transcripts render a bounded number of rows", async ({ page }) => {
  await page.route("**/api/v1/recordings/*/transcript?**", async (route) => {
    const query = new URL(route.request().url()).searchParams,
      offset = Number(query.get("offset") ?? 0),
      limit = Number(query.get("limit") ?? 1000);
    const rows = Array.from(
      { length: Math.min(limit, 5000 - offset) },
      (_, n) => ({
        id: `test-${offset + n}`,
        recording_id: "fixture",
        start_ms: (offset + n) * 2000,
        end_ms: (offset + n) * 2000 + 1500,
        text: `Example segment ${offset + n}`,
        cluster: "A",
        speaker_id: null,
        words: [],
        overlap: false,
        uncertain: false,
        excluded: false,
        manual: false,
        category: "speech",
      }),
    );
    await route.fulfill({
      json: { revision: 1, total: 5000, conflicts: [], rows },
    });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Open public demo", exact: true })
    .click();
  await expect(page.locator(".transcript-foot .mono")).toHaveText(
    "5000 / 5000",
  );
  expect(await page.locator(".turn-row").count()).toBeLessThan(60);
  await page
    .getByLabel("Search transcript", { exact: true })
    .fill("Example segment 4999");
  await expect(page.locator(".turn-row")).toHaveCount(1);
});

test("the mobile layout keeps review controls reachable without horizontal overflow", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await demo(page);
  await page.locator(".turn-row").first().click();
  await expect(page.getByLabel("Enter a name")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: testInfo.outputPath("mobile-demo.png"),
    fullPage: true,
  });
});

test("guided review saves a name and text together, then opens the next excerpt", async ({
  page,
}) => {
  await demo(page);
  await page.getByRole("button", { name: "Start review", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "1. Who is speaking?", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Enter a name", { exact: true })
    .fill("Reviewed Reader");
  await page
    .getByLabel("Transcript text", { exact: true })
    .fill("Reviewed words from the public example.");
  await page.getByRole("button", { name: "Save & next", exact: true }).click();
  await expect(page.locator(".selection-header")).toContainText(
    "Excerpt 2 / 4",
  );
  await expect(page.locator(".turn-row").first()).toContainText(
    "Reviewed Reader",
  );
  await expect(page.locator(".turn-row").first()).toContainText(
    "Reviewed words from the public example.",
  );
  await page.reload();
  await expect(page.locator(".turn-row").first()).toContainText(
    "Reviewed Reader",
  );
});

test("short desktop and narrow app panes leave room to read and keep basic controls visible", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 604 });
  await demo(page);
  expect(
    await page
      .locator(".transcript-scroll")
      .evaluate((el) => el.getBoundingClientRect().height),
  ).toBeGreaterThan(240);
  await page.getByRole("button", { name: "Start review", exact: true }).click();
  const unobscured = () =>
    page.evaluate(() => {
      const field = document
        .querySelector(".quick-text textarea")!
        .getBoundingClientRect();
      const save = document
        .querySelector(".quick-save")!
        .getBoundingClientRect();
      return field.bottom <= save.top + 1;
    });
  expect(await unobscured()).toBeTruthy();
  await page.screenshot({
    path: testInfo.outputPath("short-desktop-review.png"),
  });
  await page
    .getByRole("button", { name: "Back to transcript", exact: true })
    .click();
  await page.setViewportSize({ width: 319, height: 604 });
  expect(
    await page
      .locator(".transcript-scroll")
      .evaluate((el) => el.getBoundingClientRect().height),
  ).toBeGreaterThan(250);
  await page.getByRole("button", { name: "Start review", exact: true }).click();
  for (const label of ["Enter a name", "Transcript text"])
    await expect(page.getByLabel(label, { exact: true })).toBeInViewport({
      ratio: 1,
    });
  await expect(
    page.getByRole("button", { name: "Save & next", exact: true }),
  ).toBeInViewport();
  expect(await unobscured()).toBeTruthy();
  await expect(page.locator(".advanced-options")).not.toHaveAttribute(
    "open",
    "",
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
  ).toBeTruthy();
  await page.screenshot({ path: testInfo.outputPath("narrow-review.png") });
  await page
    .getByRole("button", { name: "Back to transcript", exact: true })
    .click();
  await expect(page.locator(".transcript-scroll")).toBeInViewport();
  await page
    .getByLabel("Interface language", { exact: true })
    .selectOption("bg");
  await page
    .getByRole("button", { name: "Започни преглед", exact: true })
    .click();
  await expect(page.locator(".quick-text textarea")).toBeInViewport({
    ratio: 1,
  });
  await expect(
    page.getByRole("button", { name: "Запази и продължи", exact: true }),
  ).toBeInViewport();
  expect(await unobscured()).toBeTruthy();
});
