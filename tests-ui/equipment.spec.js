import { test, expect } from "@playwright/test";

test("CAD industrial equipment closed-loop UI, step history, E-STOP, dock layout, and return to simulation", async ({
  page,
}, testInfo) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 920 });
  await page.goto("/?tour=off");
  await expect(page.locator("#loading")).toHaveClass(/hidden/, {
    timeout: 30000,
  });

  // Verify sidebar structured cards & PLC badges
  await expect(page.locator('[data-device="sorting_line"] .device-badge.plc')).toHaveText("PLC");
  await expect(page.locator('[data-device="robot_panda"] .device-badge')).toHaveText("CAD");

  // Enter controllable CAD equipment mode
  await page.locator('[data-device="sorting_line"]').click();
  await expect(page.locator("#twin-embed")).toBeVisible();
  await expect(page.locator("#twin-title")).toHaveText("智能视觉分拣流水线");
  await expect(page.locator("#equip-override-panel")).toBeVisible();
  await expect(page.locator("#feedback-heading")).toHaveText("PLC 与安全联锁");

  // Wait for 3D CAD parts list to populate
  await expect
    .poll(async () => page.locator("#twin-parts li[data-part]").count(), {
      timeout: 20000,
    })
    .toBeGreaterThan(2);

  // Verify bottom-right dock buttons do not overlap .twin-hint
  const hintBox = await page.locator(".twin-hint").boundingBox();
  const dockBox = await page.locator(".twin-dock").boundingBox();
  expect(dockBox.x).toBeGreaterThan(hintBox.x + hintBox.width);

  // Verify collapsible right-floating spec/parts drawer
  await page.locator("#twin-side-toggle").click();
  await expect(page.locator("#twin-side")).toHaveClass(/collapsed/);
  await page.locator("#twin-side-toggle").click();
  await expect(page.locator("#twin-side")).not.toHaveClass(/collapsed/);

  // Single-step PLC cycle & inspect history item
  await page.locator("#step").click();
  await expect(page.locator("#status-text")).toHaveText("已暂停", {
    timeout: 15000,
  });
  await expect(page.locator("#run-budget")).toContainText("01 /");
  await page.locator("#history-list > summary").click();
  await page.locator('#events [data-cycle="1"]').click();
  await expect(page.locator("#decision-heading")).toHaveText("历史输出 · 第 1 拍");
  await expect(page.locator("#decision-live")).toBeVisible();
  await page.locator("#history-observations summary").first().click();
  await expect(page.locator("#history-before")).toContainText('"sorting_line"');
  await page.locator("#decision-live").click();
  await expect(page.locator("#decision-heading")).toHaveText("当前决策");

  // E-STOP toggle & release
  await page.locator("#equip-estop").click();
  await expect(page.locator("#status-text")).toHaveText("急停锁止");
  await expect(page.locator("#equip-estop")).toHaveClass(/engaged/);
  await page.locator("#equip-estop").click();
  await expect(page.locator("#equip-estop")).not.toHaveClass(/engaged/);

  await page.screenshot({
    path: testInfo.outputPath("equipment-cad-workbench.png"),
  });

  // Return to MuJoCo simulation & verify full title/telemetry restoration
  await page.locator("#twin-back").click();
  await expect(page.locator("#twin-embed")).toBeHidden();
  await expect(page.locator(".viewport-label h1")).toHaveText("Franka Panda");
  await expect(page.locator("#scene-task")).toHaveText("INSERT");
  await expect(page.locator(".telemetry .metric-label").first()).toHaveText("末端 X");
  expect(errors).toEqual([]);
});
