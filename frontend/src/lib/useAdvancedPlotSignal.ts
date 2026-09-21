import { useEffect, useState } from "react";
import { getActiveAdvancedPlotSettingsJson } from "./appSettings";

// The settings alone. The mode used to be part of this, so opening or closing
// the panel re-rendered every plot even though nothing about them had changed.
function currentAdvancedPlotSignal(): string {
  return getActiveAdvancedPlotSettingsJson();
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
