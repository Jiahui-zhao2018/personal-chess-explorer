import { expect, test } from "@playwright/test";

test("development preview serves modules and proxies API under an external Host", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("requestfailed", (r) =>
    errors.push(r.failure()?.errorText || r.url()),
  );
  page.on("response", (r) => {
    if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Your repertoire, connected." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "e4 →", exact: true }),
  ).toBeVisible();
  await expect(page.locator("[data-square]")).toHaveCount(64);
  await page
    .getByRole("button", { name: "Opening", exact: true })
    .first()
    .click();
  await page.getByLabel("Position comment").fill("Preview proxy edit");
  await page.getByRole("button", { name: "Save annotations locally" }).click();
  await expect(page.locator(".workspace-toolbar")).toContainText(
    "Local changes pending",
  );
  expect(errors).toEqual([]);
  const untrusted = await page.request.post("http://127.0.0.1:5174/api/auth/disconnect", {
    data: {},
    headers: { Origin: "https://untrusted.example" },
  });
  expect(untrusted.status()).toBe(403);
  const badHost = await page.request.get("http://127.0.0.1:5174/", {
    headers: { Host: "untrusted.example" },
  });
  expect(badHost.status()).toBe(403);
});
