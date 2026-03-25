import type { ReactNode } from "react";

type TabItem<T extends string> = {
  key: T;
  label: string;
};

type TopTabsProps<T extends string> = {
  tabs: TabItem<T>[];
  activeTab: T;
  onChange: (tab: T) => void;
  rightContent?: ReactNode;
};

export default function TopTabs<T extends string>({
  tabs,
  activeTab,
  onChange,
  rightContent,
}: TopTabsProps<T>) {
  return (
    <div className="border-b border-slate-200 bg-white px-4 sm:px-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 flex-wrap gap-2">
          {tabs.map((tab) => {
            const active = tab.key === activeTab;

            return (
              <button
                key={tab.key}
                onClick={() => onChange(tab.key)}
                className={[
                  "border-b-2 px-4 py-3 text-sm font-medium transition",
                  active
                    ? "border-slate-900 text-slate-900"
                    : "border-transparent text-slate-500 hover:text-slate-900",
                ].join(" ")}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
        {rightContent ? <div className="shrink-0">{rightContent}</div> : null}
      </div>
    </div>
  );
}
