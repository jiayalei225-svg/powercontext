import { chromium } from "playwright-core";

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
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
const page = await browser.newPage({ viewport: { width: 1540, height: 1120 } });
page.on("console", (msg) => {
  if (msg.type() === "error") console.log("[console:error]", msg.text());
});
await page.goto("http://127.0.0.1:8787", { waitUntil: "domcontentloaded" });
await page.waitForSelector(".backend-display strong", { timeout: 300000 });
console.log("[iso] backend", await page.locator(".backend-display strong").innerText());

await page.getByRole("button", { name: "新建知识库" }).click();
await page.locator("#kb-title").fill("潮汐能隔离测试");
await page.locator("#kb-description").fill("验证新建 collection、增量导入与切换隔离。");
await page.getByRole("button", { name: "创建并切换" }).click();
await page.waitForFunction(
  () => document.querySelector(".hero h1")?.textContent?.includes("潮汐能隔离测试"),
  null,
  { timeout: 30000 },
);
console.log("[iso] new kb active");

await page.getByRole("button", { name: /导入本地文件/ }).click();
await page.waitForSelector(".modal-panel");
await page.getByRole("button", { name: "粘贴文本" }).click();
await page.locator("#paste-title").fill("潮汐发电原理");
await page
  .locator("#paste-content")
  .fill(
    "潮汐能是一种可再生能源。潮汐电站通常建在潮差较大的海湾，利用涨潮和落潮形成的水位差驱动水轮机发电。涨潮时海水进入水库，落潮时海水流出，双向流动都可以推动涡轮。潮汐的周期与月球和太阳的引力有关，因此发电出力具有可预测性。",
  );
await page.getByRole("button", { name: /开始本地导入/ }).click();
await page.getByRole("heading", { name: "导入完成" }).waitFor({ timeout: 180000 });
console.log("[iso] import", (await page.locator(".import-success h3").innerText()).trim());
await page.getByRole("button", { name: "完成", exact: true }).click();
await page.waitForFunction(
  () => document.querySelector(".collection-card.active .collection-meta")?.textContent?.includes("1 docs"),
  null,
  { timeout: 30000 },
);

await page.getByLabel("检索问题").fill("潮汐电站如何利用水位差发电？");
await page.getByLabel("检索问题").press("Enter");
await page.waitForSelector(".result-card", { timeout: 120000 });
await page.waitForTimeout(500);
const firstTitle = await page.locator(".result-title").first().innerText();
console.log("[iso] new kb first result", firstTitle);
if (!firstTitle.includes("潮汐")) throw new Error("new collection did not retrieve its own doc");

const defaultCard = page.locator(".collection-card", { hasText: "端侧检索 · Edge Atlas" });
await defaultCard.locator(".collection-select").click();
await page.waitForFunction(
  () => document.querySelector(".hero h1")?.textContent?.includes("端侧检索"),
  null,
  { timeout: 30000 },
);
await page.waitForTimeout(400);
await page.getByLabel("检索问题").fill("潮汐电站如何利用水位差发电？");
await page.getByLabel("检索问题").press("Enter");
await page.waitForTimeout(2500);
const defaultHasTide = await page.locator(".result-title", { hasText: "潮汐" }).count();
console.log("[iso] default kb contains tide result?", defaultHasTide);
if (defaultHasTide > 0) throw new Error("collection isolation failed");
console.log("[iso] collection isolation OK");

// Delete the temporary collection.
const testCard = page.locator(".collection-card", { hasText: "潮汐能隔离测试" });
await testCard.hover();
await testCard.locator(".collection-delete").click();
await page.getByRole("heading", { name: "删除知识库？" }).waitFor();
await page.getByRole("button", { name: "确认删除" }).click();
await page.waitForTimeout(1500);
console.log("[iso] collections after delete", await page.locator(".collection-card").count());
await browser.close();
