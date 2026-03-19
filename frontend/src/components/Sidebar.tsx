import type { SidebarSection } from "../lib/types";

type SidebarItem = {
  key: SidebarSection;
  label: string;
};

const items: SidebarItem[] = [
  { key: "data", label: "Data" },
  { key: "qc", label: "QC Pipeline" },
  { key: "stats", label: "Statistical Analysis" },
  { key: "peptide", label: "Peptide Level" },
  { key: "singleProtein", label: "Single Protein" },
  { key: "phospho", label: "Phospho-specific" },
  { key: "comparison", label: "Comparison" },
  { key: "summary", label: "Summary" },
  { key: "external", label: "External Tools" },
];

type SidebarProps = {
  activeSection: SidebarSection;
  onChange: (section: SidebarSection) => void;
};

export default function Sidebar({ activeSection, onChange }: SidebarProps) {
  return (
    <aside className="w-72 border-r border-slate-200 bg-white p-4">
      <div className="mb-6">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Proteomics CoPYlot
        </div>
        <div className="mt-1 text-2xl font-bold text-slate-900">Rewrite</div>
      </div>

      <nav className="space-y-2">
        {items.map((item) => {
          const active = item.key === activeSection;

          return (
            <button
              key={item.key}
              onClick={() => onChange(item.key)}
              className={[
                "w-full rounded-xl px-4 py-3 text-left text-sm transition",
                active
                  ? "bg-slate-900 text-white shadow"
                  : "text-slate-700 hover:bg-slate-100",
              ].join(" ")}
            >
              {item.label}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}