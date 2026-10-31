import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:8787";
const headed = process.env.HEADED === "1";
const outDir = path.resolve("docs", "screenshots");
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: edge,
  headless: !headed,
  args: [
    "--disable-features=Translate",
    "--enable-unsafe-webgpu",
    "--force_high_performance_gpu",
    "--ignore-gpu-blocklist",
    ...(headed ? [] : ["--use-angle=d3d11"]),
  ],
});
const context = await browser.newContext({ viewport: { width: 1540, height: 1120 } });
const page = await context.newPage();
const consoleErrors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") {
    consoleErrors.push(msg.text());
    console.log("[console:error]", msg.text());
  }
});
page.on("pageerror", (error) => consoleErrors.push(error.message));
page.on("requestfailed", (request) => {
  if (!request.url().includes("favicon")) {
    console.log("[requestfailed]", request.url(), request.failure()?.errorText);
  }
});

await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
await page.waitForSelector(".backend-display strong", { timeout: 240000 });
console.log("[smoke] backend", await page.locator(".backend-display strong").innerText());
console.log("[smoke] precision", await page.locator(".inference-panel .tag").first().innerText());

const emptyAction = page.getByRole("button", { name: /载入示例语料/ });
if (await emptyAction.count()) {
  await emptyAction.click();
  await page.getByRole("button", { name: /开始本地导入/ }).click();
} else {
  await page.getByRole("button", { name: /增量导入/ }).click();
  await page.getByRole("button", { name: "示例语料" }).click();
  await page.getByRole("button", { name: /开始本地导入/ }).click();
}

await page.getByRole("heading", { name: "导入完成" }).waitFor({ timeout: 600000 });
const successText = await page.locator(".import-success").innerText();
console.log("[smoke] import success\n" + successText);
await page.screenshot({ path: path.join(outDir, "import-complete.png"), fullPage: false });
await page.getByRole("button", { name: "完成", exact: true }).click();

await page.waitForFunction(() => {
  const cards = document.querySelectorAll(".collection-card.active .collection-meta");
  return cards.length && !cards[0].textContent?.includes("0 docs");
}, null, { timeout: 30000 });
await page.waitForTimeout(600);

const input = page.getByLabel("检索问题");
await input.fill("seekdb 如何把关键词和语义两路结果融合排序？");
await input.press("Enter");
await page.waitForSelector(".result-card", { timeout: 120000 });
await page.waitForTimeout(900);
const resultText = await page.locator(".results-section").innerText();
console.log("[smoke] results\n" + resultText.slice(0, 2500));
const timingText = await page.locator(".timing-strip").innerText();
console.log("[smoke] timing\n" + timingText);
await page.screenshot({ path: path.join(outDir, "atlas-results.png"), fullPage: true });

const metrics = await page.evaluate(() => {
  const resources = performance
    .getEntriesByType("resource")
    .filter((entry) => /\.onnx|\.wasm$|ort-wasm/.test(entry.name))
    .map((entry) => ({
      name: entry.name.split("/").slice(-1)[0],
      duration: Math.round(entry.duration),
      transferSize: entry.transferSize,
    }));
  return {
    title: document.title,
    resources,
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency,
    crossOriginIsolated: window.crossOriginIsolated,
  };
});
console.log("[smoke] browser", JSON.stringify(metrics, null, 2));
console.log("[smoke] console errors", consoleErrors.length, consoleErrors.slice(0, 5));
fs.writeFileSync(
  path.resolve("benchmark", "last-smoke.json"),
  JSON.stringify({ successText, resultText, timingText, metrics, consoleErrors }, null, 2),
);
await browser.close();
