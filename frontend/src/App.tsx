import { useState } from "react";

function App() {
  const [message, setMessage] = useState("Not tested yet");

  const testBackend = async () => {
    try {
      const res = await fetch("http://127.0.0.1:8000/ping");
      const data = await res.json();
      setMessage(JSON.stringify(data));
    } catch {
      setMessage("Backend request failed");
    }
  };

  return (
    <div style={{ padding: "2rem", fontFamily: "Arial" }}>
      <h1>Frontend works</h1>
      <button onClick={testBackend}>Test backend</button>
      <p>{message}</p>
    </div>
  );
}

export default App;