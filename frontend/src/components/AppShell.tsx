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
    <div className="flex min-h-screen bg-slate-50 text-slate-900">
      <Sidebar activeSection={activeSection} onChange={onSectionChange} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="border-b border-slate-200 bg-white px-6 py-4">
          <div className="text-lg font-semibold">Proteomics CoPYlot</div>
          <div className="text-sm text-slate-500">
            Python backend · React frontend
          </div>
        </header>

        {topBar}

        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}