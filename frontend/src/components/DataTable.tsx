import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  // A sortable column gives the value to sort by.
  sort?: (row: T) => string | number;
  align?: "left" | "right" | "center";
  className?: string;
  width?: number | string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
  initialSort,
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
  initialSort?: { key: string; dir: "asc" | "desc" };
  caption?: string;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const sorted = useMemo(() => {
    const column = sort && columns.find((c) => c.key === sort.key);
    if (!column?.sort || !sort) return rows;
    const by = column.sort;
    const factor = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const x = by(a);
      const y = by(b);
      return (x < y ? -1 : x > y ? 1 : 0) * factor;
    });
  }, [rows, sort, columns]);

  if (rows.length === 0 && empty) return <>{empty}</>;

  return (
    <div className="table-wrap">
      <table className="table">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const Icon = !active ? ArrowUpDown : sort?.dir === "asc" ? ArrowUp : ArrowDown;
              return (
                <th
                  key={c.key}
                  className={`${c.align ?? ""} ${c.sort ? "sortable" : ""}`}
                  style={{ width: c.width }}
                  aria-sort={active ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined}
                  onClick={
                    c.sort
                      ? () => setSort(active && sort?.dir === "desc" ? { key: c.key, dir: "asc" } : { key: c.key, dir: "desc" })
                      : undefined
                  }
                >
                  {c.sort ? (
                    <span className="sort">
                      {c.header}
                      <Icon aria-hidden style={{ opacity: active ? 1 : 0.4 }} />
                    </span>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={rowKey(row)} className={onRowClick ? "clickable" : undefined} onClick={onRowClick ? () => onRowClick(row) : undefined}>
              {columns.map((c) => (
                <td key={c.key} className={`${c.align ?? ""} ${c.className ?? ""}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ offset, size, total, onChange }: { offset: number; size: number; total: number; onChange: (offset: number) => void }) {
  if (total <= size && offset === 0) {
    return <div className="table-foot">{total.toLocaleString("en-GB")} total</div>;
  }
  return (
    <div className="table-foot">
      <span>
        {(offset + 1).toLocaleString("en-GB")}–{Math.min(offset + size, total).toLocaleString("en-GB")} of {total.toLocaleString("en-GB")}
      </span>
      <div className="row" style={{ gap: 6 }}>
        <button type="button" className="btn sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - size))}>
          Previous
        </button>
        <button type="button" className="btn sm" disabled={offset + size >= total} onClick={() => onChange(offset + size)}>
          Next
        </button>
      </div>
    </div>
  );
}
