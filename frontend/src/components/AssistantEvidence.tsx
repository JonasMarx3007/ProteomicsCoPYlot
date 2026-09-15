type Evidence = { tool: string; status: string; text: string };

function caption(value: string) {
  return value.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ");
}

export default function AssistantEvidence({ evidence }: { evidence: Evidence[] }) {
  return <details className="text-xs text-slate-600">
    <summary className="cursor-pointer">Supporting evidence</summary>
    {evidence.map((source, index) => {
      const lines = source.text.split("\n").filter(Boolean);
      return <section key={index} className="mt-3 space-y-2 border-t border-slate-200 pt-2">
        <h4 className="font-semibold text-slate-900">{caption(source.tool)}</h4>
        <p>{source.status === "partial" ? "Partial evidence — not the complete result." : source.status === "unavailable" ? "Evidence unavailable for this selection." : "Available evidence"}</p>
        {lines.slice(0, 8).map((line, row) => {
          const [name, ...fields] = line.split("|");
          if (!fields.length || fields.some(field => !field.includes("="))) {
            return <p key={row} className="whitespace-pre-wrap break-words">{line}</p>;
          }
          return <div key={row} className="rounded border border-slate-200 bg-white p-2">
            <div className="mb-1 font-medium">{caption(name)}</div>
            <dl className="space-y-1">{fields.map((field, column) => {
              const split = field.indexOf("=");
              return <div key={column} className="break-words">
                <dt className="inline font-medium">{caption(field.slice(0, split))}: </dt>
                <dd className="inline whitespace-pre-wrap">{field.slice(split + 1)}</dd>
              </div>;
            })}</dl>
          </div>;
        })}
        {lines.length > 8 && <p>Showing the first eight evidence records. Expand the source details for all supplied records.</p>}
        <details><summary className="cursor-pointer">Source details</summary>
          <pre className="mt-2 whitespace-pre-wrap break-words font-sans">{source.text}</pre>
        </details>
      </section>;
    })}
  </details>;
}
