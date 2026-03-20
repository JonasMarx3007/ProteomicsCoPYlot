import { useState, type ReactNode } from "react";
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

  return (
    <div className="relative min-h-screen w-full bg-slate-50 text-slate-900">
      <Sidebar
        activeSection={activeSection}
        onChange={onSectionChange}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <button
        type="button"
        onClick={() => setSidebarOpen((prev) => !prev)}
        className="fixed bottom-4 left-4 z-50 inline-flex h-11 items-center justify-center rounded-xl border border-slate-300 bg-white px-3 text-slate-700 shadow-sm transition hover:bg-slate-50"
        aria-label="Toggle sidebar"
      >
        Menu
      </button>

      <div
        className={[
          "min-h-screen min-w-0 transition-all duration-300",
          sidebarOpen ? "ml-72" : "ml-0",
        ].join(" ")}
      >
        {topBar ? <div className="shrink-0">{topBar}</div> : null}

        <main lang="en-US" className="min-w-0 p-4 sm:p-6">
          <div className="w-full">{children}</div>
        </main>
      </div>
    </div>
  );
}
