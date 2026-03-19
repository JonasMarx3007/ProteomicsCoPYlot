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
  isOpen: boolean;
  onClose: () => void;
};

export default function Sidebar({
  activeSection,
  onChange,
  isOpen,
  onClose,
}: SidebarProps) {
  return (
    <>
      <div
        className={[
          "fixed inset-0 z-30 bg-slate-900/40 transition-opacity duration-300",
          isOpen ? "opacity-100 md:hidden" : "pointer-events-none opacity-0",
        ].join(" ")}
        onClick={onClose}
      />

      <aside
        className={[
          "fixed inset-y-0 left-0 z-40 flex h-screen w-72 shrink-0 flex-col border-r border-slate-200 bg-white transition-transform duration-300",
          isOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
      >
        <div className="flex items-start justify-between p-5">
          <div className="pr-4">
            <div className="text-2xl font-bold tracking-tight text-slate-900">
              Proteomics CoPYlot
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900"
            aria-label="Close sidebar"
          >
            ✕
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
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
        </div>
      </aside>
    </>
  );
}