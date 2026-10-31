# Qoder Sites 发布记录

本文件记录 PaperDesk 项目网站通过 **Qoder Sites** 创建、发布并公开访问的过程与可核对标识。
所有标识均可在 Qoder 控制台 / OpenAPI 中按 ID 查询。

## 账号与站点

| 项目 | 值 |
| --- | --- |
| Qoder 账号 UID | `01a191a9-93d1-776f-b48c-c3727d164e84` |
| Qoder 账号名 | `nick3638668435`（个人版） |
| AppHub project ID | `01a191be-acc7-7d2d-8403-aae09c693514` |
| Site ID | `01a191be-accb-777c-927c-adb7a1c58023` |
| 站点地址 | <https://paperdesk-4qzym26fsnz.qoder.zone> |
| 可见范围 | `public`（任何人都可访问，`auth_integration_status=not_required`） |
| 首次发布 release | `01a191bf-8af0-753e-b459-f740a343f8f9` |
| 最新发布 release | `01a191ec-a05a-7146-b69c-ae8ba1384920`（runtime_version 5，含性能优化与提交信息） |
| 站点流量 | `2 / 500`（Qoder Sites 配额，2026-10-31 统计） |
| 首次发布 | 2026-10-31 19:36（Asia/Shanghai） |

## 发布链路（Deployment → Publish）

1. 把 `site/` 打包为 Qoder Sites 约定的工件：`qoder-sites.json`（formatVersion 2）+ `web/` 目录。
2. `POST /apphub/api/v1/sites/projects` 创建 AppHub 项目（返回上面的 project/site ID）。
3. `POST /sites/{siteId}/deployments` 创建 deployment：
   - deployment ID：`01a191bf-4601-7f30-8202-2406d97a62cc`
   - 工件 SHA-256：`b7c8978d70544a2d22b4976068b1d5fd7a8146d944d356010e69018803a51267`
   - 工件大小：`284013` 字节
4. `POST /deployments/{id}:issue-upload` 取得 OSS 预签名地址，`PUT` 上传 ZIP。
5. `POST /deployments/{id}:complete-upload`，校验 operation
   `01a191bf-4a15-7e77-b9c6-53562870b7c0` → `succeeded`，deployment 进入 `ready`。
6. `PUT /sites/{siteId}/access-policy` 将访问策略从 `private` 改为 `public`
   （`confirm_public=true`，policy revision 1 → 2）。
7. `POST /sites/{siteId}:publish`，发布 operation
   `01a191bf-8af0-757d-85d1-d6f447478248` → `succeeded`、`committed=true`。
8. `GET /sites/{siteId}` 返回 `active_release_id`，`GET https://paperdesk-4qzym26fsnz.qoder.zone`
   在**未登录**状态下返回 `200 text/html`。

### 最终发布（含性能优化与提交信息）

- deployment：`01a191ec-8eb4-7edc-b9d6-43f3e1ab52ea`
- 工件 SHA-256：`dcf5a1378afa328dd21f6132568d398c2c6b5d48c2eead4918e84492cc5fc510`（`283664` 字节）
- 校验 operation：`01a191ec-935a-74c9-846f-1b64d706d02d` → `succeeded`
- 发布 operation：`01a191ec-a05a-718d-b754-9ba813d1dcfe` → `succeeded`、`committed=true`
- 结果：runtime_version `5`，active_release_id `01a191ec-a05a-7146-b69c-ae8ba1384920`
- 未登录浏览器截图：`qoder-records/qoder-sites-published.png`（页面右下角可见 Qoder 的
  “Made with Qoder” 标识）

## Qoder 工具记录

- **Qoder 桌面端**：登录、账号与站点归属核对；界面截图见 `qoder-records/qoder-desktop.png`。
- **Qoder CLI（qoderclicn 1.1.81）**：用于读取 Sites 操作目录、核对 `prepare_site` /
  `publish_site` 的输入契约：
  - `qoder sites operations` 输出：`qoder-records/qoder-cli-sites-operations.json`
  - `qoder sites describe publish_site` 输出：`qoder-records/qoder-cli-describe-publish.json`
- **Qoder Sites**：托管站点并提供公开访问链接。

> 说明：代码主体由作者与 AI 结对（DeepSeek Harness）完成，Qoder 在本项目中的实际作用是
> **账号与站点归属、Sites 发布、站点运维记录**；团队的开发过程记录见
> `docs/development-log.md`。这里不把 Qoder 未参与的编码工作写成 Qoder 的产出。

## 重新发布网站

修改 `site/` 后，用新的 `actionId`/deployment 重新走一遍上面的 3–7 步即可。
发布后 Qoder 会更新 `active_release_id`，旧 release 仍保留用于回滚。
