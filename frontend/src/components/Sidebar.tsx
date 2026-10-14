import type { SidebarSection } from "../lib/types";
import { resizeHandleClass, type ResizablePanel } from "../lib/useResizablePanel";
import AppBrand from "./AppBrand";

type SidebarItem = {
  key: SidebarSection;
  label: string;
};

const items: SidebarItem[] = [
  { key: "data", label: "Data" },
  { key: "analysis", label: "Analysis" },
  { key: "completeness", label: "Completeness" },
  { key: "qc", label: "QC Pipeline" },
  { key: "stats", label: "Statistical Analysis" },
  { key: "peptide", label: "Peptide Level" },
  { key: "singleProtein", label: "Single Protein" },
  { key: "phospho", label: "Phospho-specific" },
  { key: "comparison", label: "Comparison" },
  { key: "summary", label: "Summary" },
  { key: "external", label: "External Tools" },
  { key: "settings", label: "Settings" },
];

type SidebarProps = {
  activeSection: SidebarSection;
  onChange: (section: SidebarSection) => void;
  isOpen: boolean;
  onClose: () => void;
  sections?: SidebarSection[];
  /** Drag-to-resize state owned by the shell, so the content margin follows the width. */
  panel?: ResizablePanel;
};

export default function Sidebar({
  activeSection,
  onChange,
  isOpen,
  onClose,
  sections,
  panel,
}: SidebarProps) {
  const visibleItems = sections
    ? items.filter((item) => sections.includes(item.key))
    : items;

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
        inert={!isOpen}
        aria-hidden={!isOpen}
        aria-label="Main navigation"
        className={[
          "fixed inset-y-0 left-0 z-40 flex h-screen shrink-0 flex-col border-r border-slate-200 bg-white transition-transform duration-300",
          isOpen ? "translate-x-0" : "-translate-x-full",
        ].join(" ")}
        style={{ width: panel ? `${panel.width}px` : "18rem" }}
      >
        {panel ? <div className={resizeHandleClass("right")} {...panel.handleProps("right")} /> : null}
        <div className="flex items-start justify-between gap-3 p-5">
          <AppBrand size={panel && panel.width < 300 ? "sm" : "md"} />

          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 shrink-0 place-items-center rounded-full border border-slate-200 bg-slate-50 text-slate-500 shadow-sm transition hover:border-slate-300 hover:bg-white hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
            aria-label="Close sidebar"
          >
            <svg
              aria-hidden="true"
              viewBox="0 0 24 24"
              fill="none"
              className="h-4 w-4"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M6 6l12 12" />
              <path d="M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-5">
          <nav aria-label="Analysis modules" className="space-y-2">
            {visibleItems.map((item) => {
              const active = item.key === activeSection;

              return (
                <button
                  key={item.key}
                  aria-current={active ? "page" : undefined}
                  onClick={() => { onChange(item.key); if (window.innerWidth < 768) onClose(); }}
                  className={[
                    "w-full truncate rounded-xl px-4 py-3 text-left text-sm transition",
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
