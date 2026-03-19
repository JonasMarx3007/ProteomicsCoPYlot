import type {
  CurrentDatasetsResponse,
  DatasetPreviewResponse,
  PeptidePathResponse,
} from "../../lib/types";

type Props = {
  current: CurrentDatasetsResponse | null;
};

export default function CurrentDatasetsPanel({ current }: Props) {
  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <CurrentCard
        title="Current Protein Dataset"
        content={
          current?.protein ? (
            <TableDatasetInfo dataset={current.protein} />
          ) : (
            <EmptyState text="No protein dataset selected." />
          )
        }
      />

      <CurrentCard
        title="Current Phospho Dataset"
        content={
          current?.phospho ? (
            <TableDatasetInfo dataset={current.phospho} />
          ) : (
            <EmptyState text="No phospho dataset selected." />
          )
        }
      />

      <CurrentCard
        title="Current Peptide Dataset"
        content={
          current?.peptide ? (
            <PeptideDatasetInfo dataset={current.peptide} />
          ) : (
            <EmptyState text="No peptide path selected." />
          )
        }
      />
    </div>
  );
}

function CurrentCard({
  title,
  content,
}: {
  title: string;
  content: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-base font-semibold text-slate-900">{title}</h3>
      <div className="mt-4">{content}</div>
    </div>
  );
}

function TableDatasetInfo({ dataset }: { dataset: DatasetPreviewResponse }) {
  return (
    <div className="space-y-1 text-sm text-slate-700">
      <div>
        <span className="font-medium">Filename:</span> {dataset.filename}
      </div>
      <div>
        <span className="font-medium">Format:</span> {dataset.format}
      </div>
      <div>
        <span className="font-medium">Rows:</span> {dataset.rows}
      </div>
      <div>
        <span className="font-medium">Columns:</span> {dataset.columns}
      </div>
    </div>
  );
}

function PeptideDatasetInfo({ dataset }: { dataset: PeptidePathResponse }) {
  return (
    <div className="space-y-1 text-sm text-slate-700">
      <div>
        <span className="font-medium">Filename:</span> {dataset.filename}
      </div>
      <div className="break-all">
        <span className="font-medium">Path:</span> {dataset.path}
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="text-sm text-slate-500">{text}</div>;
}