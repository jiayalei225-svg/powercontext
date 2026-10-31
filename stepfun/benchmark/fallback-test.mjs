import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright-core";

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const baseUrl = process.env.BASE_URL ?? "http://127.0.0.1:8787";
const browser = await chromium.launch({
  executablePath: edge,
  headless: true,
  args: [
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-features=Translate",
    "--enable-unsafe-webgpu",
  ],
});
const context = await browser.newContext({ viewport: { width: 1540, height: 1120 } });
const page = await context.newPage();
page.on("console", (msg) => {
  if (msg.type() === "error") console.log("[console:error]", msg.text());
});
page.on("pageerror", (error) => console.log("[pageerror]", error.message));
await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 120000 });
await page.waitForSelector(".backend-display strong", { timeout: 300000 });
await page.waitForFunction(
  () => document.querySelector(".inference-panel")?.textContent?.includes("FP16"),
  null,
  { timeout: 300000 },
);
await page.waitForTimeout(500);
const backend = await page.locator(".backend-display strong").innerText();
const precision = await page.locator(".inference-panel .tag").first().innerText();
const inspector = await page.locator(".inference-panel").innerText();
console.log("[fallback] backend", backend, "precision", precision);
console.log("[fallback] inspector\n" + inspector);

const gpu = await page.evaluate(async () => {
  if (!navigator.gpu) return { present: false, adapter: false };
  try {
    const adapter = await navigator.gpu.requestAdapter();
    return { present: true, adapter: Boolean(adapter) };
  } catch (error) {
    return { present: true, adapter: false, error: String(error) };
  }
});
console.log("[fallback] gpu", gpu);

if (backend !== "WASM") {
  console.error("[fallback] expected WASM backend");
  await browser.close();
  process.exit(1);
}

await page.getByLabel("检索问题").fill("浏览器不支持 WebGPU 时，应用怎样继续完成向量检索？");
await page.getByLabel("检索问题").press("Enter");
await page.waitForSelector(".result-card", { timeout: 120000 });
await page.waitForTimeout(800);
console.log("[fallback] timing", await page.locator(".timing-strip").innerText());
console.log("[fallback] first result", (await page.locator(".result-card").first().innerText()).slice(0, 500));
await page.screenshot({ path: "docs/screenshots/wasm-fallback.png", fullPage: true });
fs.writeFileSync(
  path.resolve("benchmark", "last-fallback.json"),
  JSON.stringify({ backend, precision, inspector, gpu }, null, 2),
);
await browser.close();
