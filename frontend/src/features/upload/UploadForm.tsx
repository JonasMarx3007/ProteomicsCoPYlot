import type { DatasetKind } from "../../lib/types";

type UploadFormProps = {
  file: File | null;
  kind: DatasetKind;
  loading: boolean;
  onFileChange: (file: File | null) => void;
  onKindChange: (kind: DatasetKind) => void;
  onSubmit: () => void;
};

export default function UploadForm({
  file,
  kind,
  loading,
  onFileChange,
  onKindChange,
  onSubmit,
}: UploadFormProps) {
  return (
    <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
      <select
        value={kind}
        onChange={(e) => onKindChange(e.target.value as DatasetKind)}
      >
        <option value="protein">Protein</option>
        <option value="phospho">Phospho</option>
      </select>

      <input
        type="file"
        accept=".csv,.tsv,.txt,.xlsx,.parquet"
        onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
      />

      <button onClick={onSubmit} disabled={!file || loading}>
        {loading ? "Uploading..." : "Upload"}
      </button>

      {file && <span>{file.name}</span>}
    </div>
  );
}