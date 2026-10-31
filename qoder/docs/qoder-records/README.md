# Qoder 记录索引

- **Qoder 账号 UID**：`01a191a9-93d1-776f-b48c-c3727d164e84`
- **Qoder 账号名**：`nick3638668435`（个人版）
- **站点**：<https://paperdesk-4qzym26fsnz.qoder.zone>（public）

## 文件

| 文件 | 内容 |
| --- | --- |
| `qoder-desktop.png` | Qoder 桌面端运行截图（登录态、Sites/任务入口） |
| `qoder-cli-sites-operations.json` | `qoder sites operations` 的实际输出：Sites 操作目录 |
| `qoder-cli-describe-publish.json` | `qoder sites describe publish_site` 的实际输出：发布入参契约 |
| `qoder-sites-published.png` | 发布后的公开站点截图（未登录访问） |

## Qoder 在本项目中的实际作用

1. 账号与站点归属：AppHub project / Site / release 都归属上述 UID。
2. Qoder Sites 发布：deployment → publish，访问范围设为 public。
3. Qoder CLI 1.1.81：读取 Sites 操作目录与 `publish_site` 契约，核对发布参数。

发布 ID 与链路细节见 `../qoder-sites.md`。

> 边界说明：代码主体由作者与 AI 结对（DeepSeek Harness）完成，本目录不把未参与的编码工作
> 记为 Qoder 产出。团队开发过程见 `../development-log.md`。
