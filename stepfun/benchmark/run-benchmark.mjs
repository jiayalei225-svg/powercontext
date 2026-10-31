import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:8787";
const label = process.env.RUN_LABEL ?? "webgpu";
const outDir = path.resolve("benchmark", "results");
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: ["--enable-unsafe-webgpu",
    "--force_high_performance_gpu", "--ignore-gpu-blocklist", "--use-angle=d3d11"],
});
const context = await browser.newContext({ viewport: { width: 1540, height: 1120 } });
const page = await context.newPage();
const errors = [];
page.on("console", (msg) => {
  if (msg.type() === "error") {
    errors.push(msg.text());
    console.log("[console:error]", msg.text());
  }
});
page.on("pageerror", (error) => {
  errors.push(error.message);
  console.log("[pageerror]", error.message);
});
page.on("requestfailed", (request) => {
  if (!request.url().includes("favicon")) {
    console.log("[requestfailed]", request.url(), request.failure()?.errorText);
  }
});

await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
await page.waitForSelector(".backend-display strong", { timeout: 300000 });
console.log("[bench] initial runtime", await page.locator(".backend-display strong").innerText());
await page.getByRole("button", { name: /Lab/ }).click();
await page.waitForFunction(() => Boolean(window.__EDGE_ATLAS_LAB__), null, { timeout: 60000 });
console.log("[bench] lab ready");

const poll = setInterval(async () => {
  try {
    const text = await page.locator(".lab-progress h3").textContent({ timeout: 1000 });
    const percent = await page.locator(".lab-progress-head > span").textContent({ timeout: 1000 });
    if (text) console.log(`[bench ${percent ?? ""}] ${text}`);
  } catch {
    // no progress panel
  }
}, 10000);

const started = Date.now();
let report;
try {
  report = await page.evaluate(async () => {
    return await window.__EDGE_ATLAS_LAB__.run();
  });
} finally {
  clearInterval(poll);
}
console.log("[bench] elapsed", Math.round((Date.now() - started) / 1000), "s");
if (!report) {
  console.error("[bench] no report returned");
  await page.screenshot({ path: path.resolve("docs/screenshots/lab-error.png"), fullPage: true });
  await browser.close();
  process.exit(1);
}
const file = path.join(outDir, `benchmark-${label}-${new Date().toISOString().replace(/[:.]/g, "-")}.json`);
fs.writeFileSync(file, JSON.stringify(report, null, 2));
fs.writeFileSync(path.join(outDir, "latest.json"), JSON.stringify(report, null, 2));

await page.waitForTimeout(800);
await page.screenshot({ path: path.resolve("docs/screenshots/lab-results.png"), fullPage: true });
console.log("[bench] report", file);
console.log("[bench] dataset", report.dataset);
console.log("[bench] environment", report.environment);
for (const result of report.results) {
  if (result.skipped) {
    console.log("[skip]", result.label, result.error);
  } else {
    console.log(
      "[config]",
      result.label,
      "load",
      result.engine.loadMs,
      "embed",
      result.ingestion.embedMs,
      "write",
      result.ingestion.writeMs,
      "q50",
      result.latency.queryEmbedP50,
      "db50",
      result.latency.searchP50,
      "e2e50",
      result.latency.e2eP50,
      "quality",
      result.quality.hybrid.recall5,
      result.quality.hybrid.ndcg5,
      result.quality.hybrid.mrr5,
    );
  }
}
console.log("[bench] errors", errors.length, errors.slice(0, 5));
await browser.close();
