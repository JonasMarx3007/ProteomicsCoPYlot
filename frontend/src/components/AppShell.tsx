import { useEffect, useState, type ReactNode } from "react";
import Sidebar from "./Sidebar";
import type { SidebarSection } from "../lib/types";

type AppShellProps = {
  activeSection: SidebarSection;
  onSectionChange: (section: SidebarSection) => void;
  topBar?: ReactNode;
  children: ReactNode;
};

export default function AppShell({
  activeSection,
  onSectionChange,
  topBar,
  children,
}: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 768px)");

    function handleChange(event: MediaQueryListEvent | MediaQueryList) {
      setSidebarOpen(event.matches);
    }

    handleChange(media);
    media.addEventListener("change", handleChange);

    return () => media.removeEventListener("change", handleChange);
  }, []);

  return (
    <div className="flex min-h-screen w-full bg-slate-50 text-slate-900">
      <Sidebar
        activeSection={activeSection}
        onChange={onSectionChange}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 py-4 sm:px-6">
          <button
            type="button"
            onClick={() => setSidebarOpen((prev) => !prev)}
            className="inline-flex rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            aria-label="Toggle sidebar"
          >
            ☰
          </button>
        </header>

        {topBar ? <div className="shrink-0">{topBar}</div> : null}

        <main className="min-w-0 flex-1 overflow-auto p-4 sm:p-6">
          <div className="w-full">{children}</div>
        </main>
      </div>
    </div>
  );
}