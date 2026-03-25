import { useEffect, useState } from "react";

type ManualEmbedProps = {
  pdfPath: string;
  title: string;
  summaryLabel?: string;
  buttonLabel?: string;
  heightPx?: number;
  defaultOpen?: boolean;
};

export default function ManualEmbed({
  pdfPath,
  title,
  summaryLabel = "Module Manual",
  buttonLabel = "Manual",
  heightPx = 720,
  defaultOpen = false,
}: ManualEmbedProps) {
  const [open, setOpen] = useState(defaultOpen);
  const resolvedHeight = Math.max(420, Math.round(heightPx));

  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
        title={title}
      >
        {buttonLabel}
      </button>

      {open ? (
        <div className="fixed inset-0 z-50">
          <button
            type="button"
            aria-label="Close manual"
            onClick={() => setOpen(false)}
            className="absolute inset-0 h-full w-full bg-slate-900/30"
          />
          <aside className="absolute right-0 top-0 h-full w-full border-l border-slate-200 bg-white shadow-2xl">
            <div className="flex h-full flex-col">
              <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
                <div>
                  <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{summaryLabel}</div>
                  <div className="text-sm font-semibold text-slate-900">{title}</div>
                </div>
                <div className="flex items-center gap-2">
                  <a
                    href={pdfPath}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 transition hover:bg-slate-50"
                  >
                    Open
                  </a>
                  <a
                    href={pdfPath}
                    download
                    className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 transition hover:bg-slate-50"
                  >
                    Download
                  </a>
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 transition hover:bg-slate-50"
                  >
                    Close
                  </button>
                </div>
              </div>
              <div className="flex-1 p-3">
                <iframe
                  src={`${pdfPath}#view=FitH`}
                  title={title}
                  className="h-full w-full rounded-xl border border-slate-200"
                  style={{ minHeight: resolvedHeight }}
                />
              </div>
            </div>
          </aside>
        </div>
      ) : null}
    </>
  );
}
