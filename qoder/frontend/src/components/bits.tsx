import type { ReactNode } from "react";
import type { SearchFilters } from "../types";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function Highlight({ text, terms }: { text: string; terms: string[] }) {
  const usable = [...new Set(terms.map((term) => term.trim()).filter((term) => term.length >= 2))];
  if (!usable.length) return <>{text}</>;
  const matcher = new RegExp(`(${usable.map(escapeRegExp).join("|")})`, "gi");
  const keys = new Set(usable.map((term) => term.toLowerCase()));
  return (
    <>
      {text.split(matcher).map((part, index) =>
        keys.has(part.toLowerCase()) ? (
          <mark key={`${part}-${index}`}>{part}</mark>
        ) : (
          <span key={`${part}-${index}`}>{part}</span>
        ),
      )}
    </>
  );
}

export function Chip({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "ink" | "accent" | "teal" }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

export function describeFilters(filters: Partial<SearchFilters> | Record<string, unknown>): string {
  const data = filters as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof data.year_from === "number") parts.push(`≥ ${data.year_from}`);
  if (typeof data.year_to === "number") parts.push(`≤ ${data.year_to}`);
  if (Array.isArray(data.venues) && data.venues.length) parts.push(data.venues.join("、"));
  if (typeof data.field === "string" && data.field) parts.push(data.field);
  if (data.has_code === true || data.only_with_code === true) parts.push("仅开源");
  if (typeof data.paper_id === "string" && data.paper_id) parts.push("单篇");
  return parts.length ? parts.join(" · ") : "无额外过滤";
}

export function timeLabel(timestamp: number): string {
  if (!timestamp) return "时间未知";
  const seconds = Math.max(0, Date.now() / 1000 - timestamp);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  const date = new Date(timestamp * 1000);
  return `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${String(date.getHours()).padStart(2, "0")}:${String(
    date.getMinutes(),
  ).padStart(2, "0")}`;
}

export function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-4)}` : value;
}
