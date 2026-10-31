import { useState } from "react";
import { api } from "../lib/api";
import type { KnowledgeBase } from "../lib/types";
import { Modal, Spinner } from "./Primitives";
import { WarningIcon } from "./Icons";

export function NewKbDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (kb: KnowledgeBase) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!title.trim()) {
      setError("请输入知识库名称。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await api.createKb({
        title: title.trim(),
        description: description.trim(),
      });
      onCreated(result.collection);
      setTitle("");
      setDescription("");
      onClose();
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="新建知识库"
      eyebrow="NEW COLLECTION / 独立索引"
      footer={
        <>
          <div className="modal-footer-note">每个知识库对应 seekdb 中独立的 collection 与索引。</div>
          <button className="button button-primary" onClick={submit} disabled={busy}>
            {busy ? <Spinner size={15} /> : null}
            创建并切换
          </button>
        </>
      }
    >
      <div className="form-field">
        <label htmlFor="kb-title">名称</label>
        <input
          id="kb-title"
          className="text-input"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="例如：论文检索 / 产品手册 / 个人笔记"
          autoFocus
          maxLength={60}
        />
      </div>
      <div className="form-field">
        <label htmlFor="kb-description">
          说明 <span className="muted">可选</span>
        </label>
        <textarea
          id="kb-description"
          className="text-input textarea"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="这个知识库收录什么内容？"
          rows={3}
          maxLength={300}
        />
      </div>
      <div className="inline-alert alert-info">
        <WarningIcon size={16} />
        <p>
          向量维度固定为 512，索引同时包含 HNSW cosine 向量索引与 IK 全文索引。切换知识库不会混用数据。
        </p>
      </div>
      {error ? (
        <div className="inline-alert alert-error">
          <WarningIcon size={16} />
          <p>{error}</p>
        </div>
      ) : null}
    </Modal>
  );
}
