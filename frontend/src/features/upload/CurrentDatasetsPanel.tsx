import type {
  CurrentDatasetsResponse,
  DatasetPreviewResponse,
  PeptidePathResponse,
} from "../../lib/types";

type Props = {
  current: CurrentDatasetsResponse | null;
};

const MAX_CARD_TEXT_LENGTH = 40;

export default function CurrentDatasetsPanel({ current }: Props) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">Current datasets</h2>
        <p className="mt-1 text-sm text-slate-500">
          One active dataset is stored per type.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <CurrentCard
          title="Protein"
          content={
            current?.protein ? (
              <TableDatasetInfo dataset={current.protein} />
            ) : (
              <EmptyState text="No protein dataset loaded" />
            )
          }
        />

        <CurrentCard
          title="Phospho"
          content={
            current?.phospho ? (
              <TableDatasetInfo dataset={current.phospho} />
            ) : (
              <EmptyState text="No phospho dataset loaded" />
            )
          }
        />

        <CurrentCard
          title="Peptide"
          content={
            current?.peptide ? (
              <PeptideDatasetInfo dataset={current.peptide} />
            ) : (
              <EmptyState text="No peptide dataset loaded" />
            )
          }
        />
      </div>
    </section>
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
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-700">
        {title}
      </h3>
      <div className="mt-3">{content}</div>
    </div>
  );
}

function TableDatasetInfo({ dataset }: { dataset: DatasetPreviewResponse }) {
  return (
    <dl className="space-y-2 text-sm text-slate-600">
      <InfoRow
        label="Filename"
        value={dataset.filename}
        truncate
      />
      <InfoRow label="Format" value={dataset.format} />
      <InfoRow label="Rows" value={String(dataset.rows)} />
      <InfoRow label="Columns" value={String(dataset.columns)} />
    </dl>
  );
}

function PeptideDatasetInfo({ dataset }: { dataset: PeptidePathResponse }) {
  return (
    <dl className="space-y-2 text-sm text-slate-600">
      <InfoRow
        label="Filename"
        value={dataset.filename}
        truncate
      />
      <InfoRow
        label="Path"
        value={dataset.path}
        truncate
      />
    </dl>
  );
}

function InfoRow({
  label,
  value,
  truncate = false,
}: {
  label: string;
  value: string;
  truncate?: boolean;
}) {
  const displayValue = truncate ? truncateText(value, MAX_CARD_TEXT_LENGTH) : value;

  return (
    <div>
      <dt className="font-medium text-slate-700">{label}</dt>
      <dd
        className={`mt-0.5 min-w-0 text-slate-600 ${
          truncate ? "overflow-hidden text-ellipsis whitespace-nowrap" : "break-words"
        }`}
        title={value}
      >
        {displayValue}
      </dd>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white px-3 py-4 text-sm text-slate-500">
      {text}
    </div>
  );
}

function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}