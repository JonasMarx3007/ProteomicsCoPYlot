import type { DatasetPreviewResponse } from "../../lib/types";

type DatasetPreviewProps = {
  dataset: DatasetPreviewResponse;
};

export default function DatasetPreview({ dataset }: DatasetPreviewProps) {
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <div><strong>Dataset ID:</strong> {dataset.datasetId}</div>
        <div><strong>Filename:</strong> {dataset.filename}</div>
        <div><strong>Kind:</strong> {dataset.kind}</div>
        <div><strong>Format:</strong> {dataset.format}</div>
        <div><strong>Rows:</strong> {dataset.rows}</div>
        <div><strong>Columns:</strong> {dataset.columns}</div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table border={1} cellPadding={8} cellSpacing={0}>
          <thead>
            <tr>
              {dataset.columnNames.map((col) => (
                <th key={col}>{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dataset.preview.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {dataset.columnNames.map((col) => (
                  <td key={col}>{String(row[col] ?? "")}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}