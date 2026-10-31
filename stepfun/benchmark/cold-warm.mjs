import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:8788";
const outDir = path.resolve("docs", "benchmarks");
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: [
    "--enable-unsafe-webgpu",
    "--force_high_performance_gpu",
    "--ignore-gpu-blocklist",
    "--use-angle=d3d11",
  ],
});
const context = await browser.newContext({ viewport: { width: 1400, height: 1000 } });
const page = await context.newPage();
const cdp = await context.newCDPSession(page);

async function readRuntime(label) {
  await page.waitForSelector(".backend-display strong", { timeout: 300000 });
  await page.waitForTimeout(400);
  const inspector = await page.locator(".inference-panel").innerText();
  const loadMatch = inspector.match(/cold load\s*\n?\s*([\d.]+ (?:ms|s))/i);
  const backend = await page.locator(".backend-display strong").innerText();
  const precision = await page.locator(".inference-panel .tag").first().innerText();
  const resources = await page.evaluate(() =>
    performance
      .getEntriesByType("resource")
      .filter((entry) => entry.name.endsWith(".onnx"))
      .map((entry) => ({
        file: entry.name.split("/").slice(-1)[0],
        durationMs: Math.round(entry.duration),
        transferSize: entry.transferSize,
      })),
  );
  return {
    label,
    backend,
    precision,
    shownLoadMs: loadMatch ? loadMatch[1] : null,
    resources,
    inspector,
  };
}

await cdp.send("Network.enable");
await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
await cdp.send("Network.clearBrowserCache");
const navigationStart = Date.now();
await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
const cold = await readRuntime("cold");
cold.navigationToReadyMs = Date.now() - navigationStart;

await cdp.send("Network.setCacheDisabled", { cacheDisabled: false });
const warmStart = Date.now();
await page.reload({ waitUntil: "domcontentloaded", timeout: 120000 });
const warm = await readRuntime("warm-in-session");
warm.navigationToReadyMs = Date.now() - warmStart;

const output = {
  measuredAt: new Date().toISOString(),
  baseUrl,
  userAgent: await page.evaluate(() => navigator.userAgent),
  webgpuAdapter: await page.evaluate(async () => {
    const adapter = await navigator.gpu?.requestAdapter({ powerPreference: "high-performance" });
    const info = adapter?.info ?? {};
    return [info.vendor, info.architecture, info.device].filter(Boolean).join(" · ");
  }),
  note: "ONNX payloads are served no-store (Chromium large-body disk-cache workaround); warm means a reload in the same browser session.",
  cold,
  warm,
};
fs.writeFileSync(path.join(outDir, "cold-warm.json"), JSON.stringify(output, null, 2));
console.log(JSON.stringify(output, null, 2));
await browser.close();
