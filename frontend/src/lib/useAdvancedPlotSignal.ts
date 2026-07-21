import { useEffect, useState } from "react";
import { getActiveAdvancedPlotSettingsJson, getAdvancedPlotMode } from "./appSettings";

function currentAdvancedPlotSignal(): string {
  return `${getAdvancedPlotMode() ? "1" : "0"}:${getActiveAdvancedPlotSettingsJson()}`;
}

export function useAdvancedPlotSignal(): string {
  const [signal, setSignal] = useState(() => currentAdvancedPlotSignal());

  useEffect(() => {
    const refresh = () => setSignal(currentAdvancedPlotSignal());
    window.addEventListener("copylot:advancedPlotModeChanged", refresh);
    window.addEventListener("copylot:advancedPlotSettingsChanged", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("copylot:advancedPlotModeChanged", refresh);
      window.removeEventListener("copylot:advancedPlotSettingsChanged", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  return signal;
}
