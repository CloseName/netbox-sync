import {tr} from "./i18n";
import type { ReactNode } from "react";
import type { Status } from "./status";
import { exactTime, relativeTime } from "./format";
export function Badge({ value, code }: { value: Status; code?: string }) {
  return (
    <span className={`badge badge-${value.tone}`} title={code}>
      <span aria-hidden="true">{value.icon}</span> {tr(value.label)}
    </span>
  );
}
export function Timestamp({ value }: { value: string | null | undefined }) {
  return value ? (
    <time dateTime={value} title={exactTime(value)}>
      {relativeTime(value)}
      <span className="sr-only"> ({exactTime(value)})</span>
    </time>
  ) : (
    <>{tr("Not recorded")}{" "}</>
  );
}
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {description && <p className="muted">{description}</p>}
      </div>
      <div className="page-actions">{actions}</div>
    </div>
  );
}
export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <p>{title}</p>
      {children}
    </div>
  );
}
export function LoadingState({
  label = "Loading data…",
  table = false,
}: {
  label?: string;
  table?: boolean;
}) {
  return (
    <div role="status">
      <span>{tr(label)}</span>
      {table && (
        <div aria-hidden="true" className="skeleton">
          {[1, 2, 3, 4, 5].map((n) => (
            <div key={n} />
          ))}
        </div>
      )}
    </div>
  );
}
export function Alert({
  children,
  retry,
  tone = "danger",
}: {
  children: ReactNode;
  retry?: () => void;
  tone?: "danger" | "warning";
}) {
  return (
    <div className={`alert alert-${tone}`} role="alert">
      <div>{children}</div>
      {retry && <button onClick={retry}>{tr("Retry")}{" "}</button>}
    </div>
  );
}
export function Pagination({
  page,
  size,
  total,
  change,
}: {
  page: number;
  size: number;
  total: number;
  change: (key: string, value: string) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="pagination">
      <label htmlFor="page-size">{tr("Rows per page")}{" "}</label>
      <select
        id="page-size"
        value={size}
        onChange={(e) => change("size", e.target.value)}
      >
        {[25, 50, 100].map((n) => (
          <option key={n}>{n}</option>
        ))}
      </select>
      <span>
        {total ? (page - 1) * size + 1 : 0}–{Math.min(page * size, total)} {tr("of")}{" "}{" "}
        {total}
      </span>
      <button
        disabled={page <= 1}
        onClick={() => change("page", String(page - 1))}
      >
        {tr("Previous")}{" "}</button>
      <span>
        {tr("Page")}{" "}{page} {tr("of")}{" "}{pages}
      </span>
      <button
        disabled={page >= pages}
        onClick={() => change("page", String(page + 1))}
      >
        {tr("Next")}{" "}</button>
    </div>
  );
}
