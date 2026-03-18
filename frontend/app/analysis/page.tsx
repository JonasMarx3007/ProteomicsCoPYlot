async function getHealth() {
  const res = await fetch("http://localhost:8000/api/health", {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error("Backend not reachable");
  }

  return res.json();
}

async function getLayoutInfo() {
  const res = await fetch("http://localhost:8000/api/layout", {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error("Could not load layout info");
  }

  return res.json();
}

const panelStyle = {
  background: "white",
  border: "1px solid #ddd",
  borderRadius: 12,
  padding: 16,
  minHeight: 220,
  boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
};

export default async function AnalysisPage() {
  const health = await getHealth();
  const layout = await getLayoutInfo();

  return (
    <main style={{ padding: 24 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0 }}>{layout.app_name}</h1>
        <p style={{ color: "#555" }}>Backend status: {health.status}</p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginBottom: 16,
        }}
      >
        <section style={panelStyle}>
          <h2>{layout.panels[0]}</h2>
          <p>Empty placeholder for volcano plot</p>
        </section>

        <section style={panelStyle}>
          <h2>{layout.panels[1]}</h2>
          <p>Empty placeholder for boxplot</p>
        </section>
      </div>

      <section style={panelStyle}>
        <h2>{layout.panels[2]}</h2>
        <p>Empty placeholder for selected protein details</p>
      </section>
    </main>
  );
}