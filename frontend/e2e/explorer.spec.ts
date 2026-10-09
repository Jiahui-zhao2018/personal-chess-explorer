import { expect, test } from "@playwright/test";

test("real board, explorer, chapter edits, refresh and read-only synchronization", async ({
  page,
}) => {
  const failures: string[] = [];
  page.on("pageerror", (error) => {
    failures.push(error.message);
    console.log("Browser error:", error.message);
  });
  page.on("console", (msg) => {
    if (msg.type() === "error") console.log("Browser console:", msg.text());
  });
  await page.goto("/");
  await page.screenshot({ path: "test-results/startup.png", fullPage: true });
  await expect(
    page.getByRole("button", { name: "e4 →", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/explorer-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "e4 →", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "c5 →", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Main idea", { exact: true })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(
    page.getByRole("button", { name: "e4 →", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Opening", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("heading", { name: "Chapter workspace" }),
  ).toBeVisible();
  await page.getByLabel("Position comment").fill("Root edited in browser");
  await page.getByRole("button", { name: "Save annotations locally" }).click();
  await expect(page.locator(".workspace-toolbar")).toContainText(
    "Local changes pending",
  );
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(page.getByLabel("Position comment")).toHaveValue("");
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(page.getByLabel("Position comment")).toHaveValue(
    "Root edited in browser",
  );
  await page.getByRole("button", { name: "Sync from Lichess" }).click();
  await expect(page.getByLabel("Position comment")).toHaveValue(
    "Root edited in browser",
  );
  await page.getByRole("button", { name: "Review synchronization" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Confirm push to Lichess" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Close sync preview" }).click();
  await page.getByRole("button", { name: /Training/ }).click();
  await page.getByRole("button", { name: "Start review" }).click();
  await expect(
    page.getByText("Find a prepared continuation.", { exact: false }),
  ).toBeVisible();
  await page.locator('[data-square="e2"]').click();
  await page.locator('[data-square="e4"]').click();
  await expect(page.getByText("That’s in your repertoire.")).toBeVisible();
  expect(failures).toEqual([]);
});

test("mobile layout and study manager remain usable", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "e4 →", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/explorer-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: /Studies/ }).click();
  await expect(
    page.getByRole("heading", { name: "Add a Lichess Study" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove locally" }),
  ).toBeVisible();
});
