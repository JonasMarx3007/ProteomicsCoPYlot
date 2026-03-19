import type { DatasetPreviewResponse } from "../../lib/types";

type MetaPageProps = {
  dataset: DatasetPreviewResponse | null;
};

export default function MetaPage({ dataset }: MetaPageProps) {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <h2 className="text-lg font-semibold">Metadata</h2>
        <p className="mt-1 text-sm text-slate-500">
          This is the placeholder for sample metadata, conditions, annotations,
          and grouping logic.
        </p>
      </div>

      {dataset ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-sm text-slate-500">Current dataset</div>
          <div className="mt-2 text-base font-medium text-slate-900">
            {dataset.filename}
          </div>
          <div className="mt-1 text-sm text-slate-600">
            {dataset.rows} rows · {dataset.columns} columns · {dataset.kind}
          </div>
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          Upload a dataset first before adding metadata.
        </div>
      )}
    </div>
  );
}