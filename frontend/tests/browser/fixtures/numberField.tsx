import { useState } from "react";
import { createRoot } from "react-dom/client";
import NumberField from "../../../src/components/NumberField";

// Standalone browser-test entry point, not a hot-reloaded application module.
// eslint-disable-next-line react-refresh/only-export-components
function Harness() {
  const [value, setValue] = useState(500);
  return <>
    <NumberField label="Maximum term size" value={value} onChange={setValue} />
    <output aria-label="Applied value">{value}</output>
    <button>Leave field</button>
    <button onClick={() => setValue(600)}>External update</button>
  </>;
}

createRoot(document.getElementById("root")!).render(<Harness />);
