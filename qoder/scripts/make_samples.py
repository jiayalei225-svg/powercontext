"""Generate reproducible sample PDFs from our own reading notes.

Shipping generated PDFs instead of downloaded papers keeps the repo free of
third-party copyright while still exercising multi-page parsing.
"""

from __future__ import annotations

from pathlib import Path

import fitz

OUT = Path(__file__).resolve().parents[1] / "data" / "samples"

PAPERS = [
    {
        "file": "transformer_note.pdf",
        "title": "阅读笔记：注意力机制与 Transformer 架构",
        "meta": {"venue": "NeurIPS", "field": "自然语言处理", "year": 2017, "has_code": True},
        "pages": [
            [
                ("一、问题背景", "循环神经网络按时间步串行处理序列，长距离依赖需要经过多步传递，"
                 "梯度容易衰减，训练难以并行。卷积网络虽然可以并行，但要覆盖长距离依赖需要堆叠很多层。"),
                ("二、核心思想", "自注意力把序列中每个位置与所有位置直接相连，任意两个位置的交互路径长度为常数。"
                 "缩放点积注意力用查询、键、值三组投影计算权重：查询与键做点积并除以维度的平方根，"
                 "经 softmax 归一化后对值加权求和。除以平方根是为了避免点积随维度增大而使 softmax 进入饱和区。"),
            ],
            [
                ("三、多头机制", "多头注意力把表示切分成多个子空间并行计算注意力，再拼接投影。"
                 "不同头可以关注不同的语言现象，例如句法依存或指代关系。"),
                ("四、位置编码", "自注意力本身对顺序不敏感，需要显式注入位置信息。"
                 "原始工作使用正弦位置编码，后续工作多用可学习位置嵌入或旋转位置编码。"),
            ],
            [
                ("五、残差与归一化", "每个子层外围包裹残差连接和层归一化，使深层网络可以稳定训练。"
                 "预归一化把归一化放在子层输入侧，训练更稳定，成为主流做法。"),
                ("六、影响与局限", "该架构成为大规模预训练语言模型的基础。局限在于注意力计算量随序列长度平方增长，"
                 "长文本场景需要稀疏注意力、线性注意力或分块计算等近似方法。"),
            ],
        ],
    },
    {
        "file": "rag_note.pdf",
        "title": "阅读笔记：检索增强生成与稠密检索",
        "meta": {"venue": "NeurIPS", "field": "信息检索", "year": 2020, "has_code": True},
        "pages": [
            [
                ("一、动机", "纯参数化模型把知识压缩在权重里，更新成本高，且难以给出出处。"
                 "检索增强生成把外部文档作为非参数化记忆，生成时按需检索，答案可以回溯到原文。"),
                ("二、双塔检索", "稠密检索用两个编码器分别编码查询和文档，映射到同一向量空间，"
                 "用内积或余弦相似度排序。训练常用对比学习，正样本是相关文档，负样本来自批内或难负样本挖掘。"),
            ],
            [
                ("三、混合检索的价值", "纯向量检索擅长语义匹配，但对专有名词、编号、公式符号不敏感；"
                 "关键词检索恰好相反。工业系统普遍把两路结果做融合，例如倒数排名融合 RRF："
                 "对每一路按名次取倒数求和，无需跨模型校准分数。"),
                ("四、结构化过滤", "文献检索常带硬约束，例如年份区间、发表 venue、是否开源。"
                 "把过滤条件下推到检索层，可以避免先召回再过滤造成的候选不足。"),
            ],
            [
                ("五、评估", "常用指标包括召回率、平均倒数排名和答案的引用准确率。"
                 "端到端评估需要同时看检索质量与生成是否忠实于检索到的证据。"),
                ("六、工程要点", "分块粒度直接影响效果：块太大引入噪声，太小丢失上下文。"
                 "保留页码、段落编号等出处信息，是把检索结果变成可用证据的前提。"),
            ],
        ],
    },
    {
        "file": "gnn_note.pdf",
        "title": "阅读笔记：图神经网络与消息传递框架",
        "meta": {"venue": "ICLR", "field": "图学习", "year": 2019, "has_code": False},
        "pages": [
            [
                ("一、为什么要图神经网络", "很多数据的天然结构是图：分子、社交网络、引文网络。"
                 "图没有固定的节点顺序，卷积的平移不变性假设不成立，需要重新设计聚合算子。"),
                ("二、消息传递", "统一视角下，每一层包含三步：从邻居收集消息、聚合消息、更新自身表示。"
                 "聚合函数需要满足置换不变性，常见选择是求和、均值或最大值。"),
            ],
            [
                ("三、过平滑问题", "层数增加时，节点表示趋于一致，区分度下降。"
                 "缓解手段包括残差连接、跳跃连接、DropEdge 以及限制有效感受野。"),
                ("四、训练与采样", "大图无法整图放入显存，常用邻居采样或子图采样构造小批量。"
                 "采样会引入方差，需要控制采样数量与批大小。"),
            ],
            [
                ("五、在科研中的用法", "把论文按引用关系构图，节点是文献，边是引用，"
                 "可以做主题聚类、影响力估计和相似文献推荐。与文本向量结合时，图结构提供文本之外的信号。"),
                ("六、开放问题", "异构图、动态图和超图上的消息传递仍是活跃方向，"
                 "此外可解释性不足限制了它在高风险场景的落地。"),
            ],
        ],
    },
    {
        "file": "peft_note.pdf",
        "title": "阅读笔记：参数高效微调与低秩适配",
        "meta": {"venue": "ICLR", "field": "模型训练", "year": 2021, "has_code": True},
        "pages": [
            [
                ("一、全量微调的成本", "大模型全量微调要保存完整参数副本，显存与存储开销随参数量线性增长，"
                 "多任务场景需要为每个任务保存一份权重。"),
                ("二、低秩适配", "低秩适配冻结预训练权重，在旁路注入两个低秩矩阵相乘得到的增量，"
                 "只训练这两个小矩阵。推理时可以把增量合并回原权重，不增加延迟。"),
            ],
            [
                ("三、秩的选择", "秩决定可训练参数量与表达能力。实践中从较小的秩开始，"
                 "在效果不足时再提高，同时配合缩放系数平衡增量幅度。"),
                ("四、与其他方法比较", "适配器插入额外层会增加推理深度；前缀调优改变输入表示；"
                 "低秩适配的优势是参数少且可以合并，缺点是秩较低时对复杂任务的拟合能力有限。"),
            ],
            [
                ("五、实践建议", "在数据量较小的领域适配上，参数高效微调通常比全量微调更省资源，"
                 "且多个任务可以共享同一底座。评估时要关注灾难性遗忘，建议保留一部分通用评测集。"),
            ],
        ],
    },
]


def build() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for paper in PAPERS:
        path = OUT / paper["file"]
        doc = fitz.open()
        for page_index, blocks in enumerate(paper["pages"]):
            page = doc.new_page(width=595, height=842)
            y = 72
            if page_index == 0:
                page.insert_text((72, y), paper["title"], fontname="china-s", fontsize=16)
                y += 40
            for heading, body in blocks:
                page.insert_text((72, y), heading, fontname="china-s", fontsize=12)
                y += 22
                for line in _wrap(body, 34):
                    page.insert_text((72, y), line, fontname="china-s", fontsize=10.5)
                    y += 17
                y += 16
        doc.set_metadata({"title": paper["title"]})
        doc.save(path)
        doc.close()
        written.append(path)
    return written


def _wrap(text: str, width: int) -> list[str]:
    return [text[i : i + width] for i in range(0, len(text), width)]


if __name__ == "__main__":
    for item in build():
        print(item)
