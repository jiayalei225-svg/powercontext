# 数据说明

本目录不包含外部数据集。

- 七个人物（老周、白露、阿信、红姨、皮皮、沈先生、小满）的姓名、职业、性格、秘密、口癖均为本作品原创。
- `scripts/seed_demo.py` 生成的两局历史战绩和第三局进行中状态，是本作品为验收编写的演示数据，不来自任何真实玩家。
- 没有使用公开工作流的 DSL、第三方知识库、判例库、语料或图片。
- 人物与剧情纯属虚构；不影射真实人物、公司或事件。

如果后续要替换人物，修改 `engine/moonfall.py` 里的 `NPCS` 常量，重新运行：

```powershell
python tools/build_dsl.py
python tools/validate_dsl.py
```

DSL 中的 LLM 人设提示词也需要同步更新（`tools/build_dsl.py` 的 `NARRATOR_SYSTEM`）。
