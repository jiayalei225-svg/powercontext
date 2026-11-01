# 提交前自检清单 · StudyCoach

> 用法：每次准备提交/发布前，从上到下过一遍。`[ ]` 改成 `[x]` 之前，先真正执行对应命令并看到预期结果。

---

## A. 仓库与分支

- [ ] 当前分支是 `2026-competition-ecosystem`

```bash
git branch --show-current
# 期望：2026-competition-ecosystem
```

- [ ] 业务改动只发生在 `qoder/` 下

```bash
git status --short
# 期望：所有条目都以 qoder/ 开头；没有仓库根目录或其他目录的文件
```

- [ ] 旧版 PaperDesk 仍完整保留在 `qoder/archive/paperdesk/`，没有被新代码引用

```bash
grep -rn "archive/paperdesk\|PaperDesk" qoder/app qoder/scripts qoder/requirements.txt 2>/dev/null
# 期望：无输出
```

- [ ] 提交粒度清晰，每个阶段一条 commit，信息可读

```bash
git log --oneline -8
```

---

## B. 密钥与隐私

- [ ] `.env` 没有被跟踪

```bash
git ls-files qoder | grep -E '(^|/)\.env$'
# 期望：无输出
```

- [ ] `.env.example` 只有占位值，没有真实 key

```bash
grep -nE 'LLM_API_KEY|EMBEDDING_API_KEY|api[_-]?key|token|secret|password' qoder/.env.example
# 期望：变量存在，但值均为空
```

- [ ] 全仓库（排除归档与文档示例）没有真实密钥

```bash
git grep -nE 'sk-[A-Za-z0-9]{10,}|Bearer [A-Za-z0-9._-]{20,}' -- qoder
# 期望：无输出
```

- [ ] 文档与截图里没有本机绝对路径、账号、cookie、token

```bash
git grep -nE 'C:\\Users\\|/Users/|Authorization:|Cookie:' -- qoder/README.md qoder/docs
# 期望：无输出（截图是图片，命令只查文本）
```

---

## C. 功能与数据

- [ ] 干净数据下能启动：删 `data/seekdb`、`data/powercontext`、`data/uploads` 后重启，`/health` 正常

```bash
curl -s http://127.0.0.1:8090/health
# 期望：status=ok，seekdb.status=ok，powercontext.ready=true，version=0.6.0，stage=S6
```

- [ ] 启动顺序正确：应用先起，PowerContext 后起

```bash
curl -s http://127.0.0.1:8010/health/ready
# 期望：inference.embedding=ready；不是 timeout / degraded
```

- [ ] 自动验收全部通过

```bash
cd qoder
.venv/Scripts/python.exe scripts/verify.py
# 期望：ALL PASS
```

- [ ] 三份种子资料导入为 3 文档 / 27 chunks；重复导入全部跳过

- [ ] 跨会话记忆生效：第二轮问答注入 `profile` 与 `weakness`

- [ ] 判分更新掌握度，答错的下次复习为 30 分钟后

- [ ] 计划连续生成两次复用同一条 artifact ID（`reused=true`）

- [ ] 技术轨迹包含 `seekdb / powercontext / app` 三层（配置 LLM 时再加 `llm`）

- [ ] 资料库删除文档后，chunk 数与知识点同步下降

- [ ] 窄屏（约 375 px）下三页可操作，无横向滚动

- [ ] 未配置 LLM 时界面明确显示 `evidence` 模式；不出现“看起来像模型生成”的假象

---

## D. TODO 与未完成项

- [ ] 代码里没有未标注的 TODO / FIXME

```bash
grep -rn "TODO\|FIXME" qoder/app qoder/scripts qoder/docker 2>/dev/null | grep -v __pycache__
# 期望：无输出
```

- [ ] 已知未验证项在 README 与网站文案中明确标注：

  - Docker 编排未在本机端到端验证（Windows 未安装 Docker），主路径为嵌入式一键启动；
  - PDF 仅文本层，无 OCR；
  - 单用户本地运行，多用户隔离不在范围；
  - LLM 为可选增强，未配置时使用 evidence 模式。

- [ ] 没有为了“看起来完整”而伪造接口、假数据或写死答案

```bash
grep -rn "mock\|fake\|hardcode\|dummy" qoder/app qoder/scripts 2>/dev/null | grep -v __pycache__
# 期望：无输出（或仅注释中说明“不 mock”）
```

---

## E. 文档与截图

- [ ] `README.md` 与当前实现一致：版本 0.6.0 / S6、端口 8090+8010、启动顺序、接口表、配置表

- [ ] `docs/verification.md` 的命令可在本机直接执行

- [ ] `docs/website-content.md` 的文案与截图一一对应

- [ ] `docs/qoder-dev-log.md` 覆盖 S1–S6，含真实踩坑与修复

- [ ] `docs/screenshots/` 含 11 个文件（10 个场景 + 判分明细），均为 1440×1000 PNG

```bash
ls qoder/docs/screenshots
```

- [ ] 截图里没有 toast 遮挡、没有未加载的空白、没有开发者工具

- [ ] README 中提到的每个链接都指向真实存在的文件

```bash
grep -oE '\]\([^)]+\)' qoder/README.md
```

---

## F. 发布到 Qoder Sites

- [ ] 用个人账号创建/发布站点，不依赖登录态也能访问

- [ ] 把 `docs/screenshots/` 的图片上传到站点，按 01–10 顺序排列

- [ ] 首屏、问题、方案、双引擎分工、演示脚本、技术栈、诚实边界均已在页面出现

- [ ] 页脚填入真实仓库地址与站点地址（替换 `docs/website-content.md` 里的 `<发布时填入 ...>`）

- [ ] 无痕窗口打开站点：图片正常、无 404、无登录墙、移动端可读

- [ ] 发布后再次修改内容时，重新发布（不要只改本地）

- [ ] 评审结束前不要暂停或删除站点

---

## G. 最终命令清单

```bash
# 1. 分支与改动范围
git branch --show-current
git status --short

# 2. 密钥扫描
git ls-files qoder | grep -E '(^|/)\.env$'
git grep -nE 'sk-[A-Za-z0-9]{10,}|Bearer [A-Za-z0-9._-]{20,}' -- qoder

# 3. 启动并验收
cd qoder
.venv/Scripts/python.exe scripts/verify.py

# 4. 数据证据
.venv/Scripts/python.exe scripts/evidence.py

# 5. 提交
git add qoder
git commit -m "docs(qoder): S6 startup order, UTC scheduling and delivery docs"
```

---

## H. 发布前最后一问

- 如果评审只打开网站、不运行代码，他能否在 90 秒内看懂：**问题是什么、seekdb 做了什么、PowerContext 做了什么、两者如何同时出现在一次回答里？**
- 如果他克隆仓库并按 README 启动，能否在 5 分钟内看到：**3 份资料、27 个 chunk、一次带引用的回答、一次跨会话记忆注入、一次判分后的掌握度变化？**

两个问题的答案都应为“能”。若不能，先补文案或验收步骤，再发布。
