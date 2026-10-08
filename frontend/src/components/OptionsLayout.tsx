import type { ReactNode } from "react";

/**
 * The options block above a plot: fields in a grid, a row of toggles and the size row.
 *
 * One layout for every plot page. `order` keeps each page's established
 * arrangement (QC pages put their toggles first; the peptide page puts the size
 * row before its toggles).
 */
export default function OptionsLayout({
  fields = [], toggles = [], size = null, columns = 3, order = "fields-toggles-size",
}: {
  fields?: ReactNode[];
  toggles?: ReactNode[];
  size?: ReactNode | null;
  columns?: 2 | 3;
  order?: "fields-toggles-size" | "toggles-fields-size" | "fields-size-toggles";
}) {
  const parts: Record<string, ReactNode> = {
    fields: fields.length > 0
      ? <div key="fields" className={`grid gap-4 ${columns === 2 ? "lg:grid-cols-2" : "lg:grid-cols-3"}`}>{fields}</div>
      : null,
    toggles: toggles.length > 0 ? <div key="toggles" className="flex flex-wrap gap-3">{toggles}</div> : null,
    size: size ? <div key="size">{size}</div> : null,
  };
  return <div className="space-y-4">{order.split("-").map((part) => parts[part])}</div>;
}
