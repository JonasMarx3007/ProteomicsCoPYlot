import { useId, useState } from "react";
import Modal from "./Modal";

type ManualEmbedProps = {
  pdfPath: string;
  title: string;
  /** The complete manual, offered next to the chapter. */
  fullManualPath?: string;
  summaryLabel?: string;
  buttonLabel?: string;
  defaultOpen?: boolean;
};

export default function ManualEmbed({
  pdfPath,
  title,
  fullManualPath,
  summaryLabel = "Module Manual",
  buttonLabel = "Manual",
  defaultOpen = false,
}: ManualEmbedProps) {
  const [open, setOpen] = useState(defaultOpen);
  const titleId = useId();

  return (
    <>
      <button
        type="button"
        onClick={event => { event.currentTarget.focus(); setOpen(true); }}
        className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
        title={title}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        {buttonLabel}
      </button>

      {open ? (
        <Modal labelledBy={titleId} onClose={() => setOpen(false)} className="copylot-manual">
          <div className="h-full bg-white">
            <div className="flex h-full flex-col">
              <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
                <div>
                  <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{summaryLabel}</div>
                  <h2 id={titleId} className="text-sm font-semibold text-slate-900">{title}</h2>
                </div>
                <div className="flex items-center gap-2">
                  {fullManualPath ? (
                    <a
                      href={fullManualPath}
                      target="_blank"
                      rel="noreferrer"
                      className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 transition hover:bg-slate-50"
                    >
                      Complete manual
                    </a>
                  ) : null}
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
              <div className="min-h-0 flex-1">
                <iframe
                  src={`${pdfPath}#view=FitH`}
                  title={title}
                  className="block h-full w-full border-0"
                />
              </div>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
