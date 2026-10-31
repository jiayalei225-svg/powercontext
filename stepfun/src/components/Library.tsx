import type { KnowledgeBase } from "../lib/types";
import { formatTime } from "../lib/model";
import { DatabaseIcon, FileIcon, PlusIcon, TrashIcon } from "./Icons";

export function Library({
  collections,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  collections: KnowledgeBase[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (kb: KnowledgeBase) => void;
}) {
  return (
    <aside className="library">
      <div className="library-head">
        <div>
          <span className="eyebrow">COLLECTIONS</span>
          <h2>知识库</h2>
        </div>
        <button className="icon-button" onClick={onNew} aria-label="新建知识库">
          <PlusIcon size={18} />
        </button>
      </div>

      <div className="collection-list">
        {collections.map((kb, index) => {
          const active = kb.id === activeId;
          return (
            <div key={kb.id} className={`collection-card ${active ? "active" : ""}`}>
              <button className="collection-select" onClick={() => onSelect(kb.id)}>
                <span className="collection-index">{String(index + 1).padStart(2, "0")}</span>
                <span className="collection-main">
                  <strong>{kb.title}</strong>
                  <span className="collection-meta">
                    {kb.documents} docs <i /> {kb.chunks} chunks
                  </span>
                  <span className="collection-time">{formatTime(kb.lastImportAt)}</span>
                </span>
                <span className="collection-indicator" />
              </button>
              {collections.length > 1 ? (
                <button
                  className="collection-delete"
                  onClick={() => onDelete(kb)}
                  aria-label={`删除 ${kb.title}`}
                  title="删除知识库"
                >
                  <TrashIcon size={14} />
                </button>
              ) : null}
            </div>
          );
        })}
        {collections.length === 0 ? (
          <div className="collection-empty">
            <DatabaseIcon size={20} />
            <span>还没有知识库</span>
            <button className="text-button" onClick={onNew}>
              创建第一个
            </button>
          </div>
        ) : null}
      </div>

      <button className="new-collection-row" onClick={onNew}>
        <PlusIcon size={15} />
        新建 collection
      </button>

      <div className="library-foot">
        <div className="library-foot-icon">
          <FileIcon size={15} />
        </div>
        <p>
          <strong>每个知识库独立索引</strong>
          <span>切换 collection 不会混合检索结果。</span>
        </p>
      </div>
    </aside>
  );
}
