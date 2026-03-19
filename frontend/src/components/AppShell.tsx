import type { ReactNode } from "react";
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
  return (
    <div className="flex min-h-screen w-full bg-slate-50 text-slate-900">
      <Sidebar activeSection={activeSection} onChange={onSectionChange} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-slate-200 bg-white px-4 py-4 sm:px-6">
          <div className="text-lg font-semibold">Proteomics CoPYlot</div>
          <div className="text-sm text-slate-500">
            Python backend · React frontend
          </div>
        </header>

        {topBar ? <div className="shrink-0">{topBar}</div> : null}

        <main className="min-w-0 flex-1 overflow-auto p-4 sm:p-6">
          <div className="w-full">{children}</div>
        </main>
      </div>
    </div>
  );
}