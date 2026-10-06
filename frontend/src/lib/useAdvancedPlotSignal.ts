import { useEffect, useState } from "react";
import { getActiveAdvancedPlotSettingsJson } from "./appSettings";
import { currentLocalizationCutoff, LOCALIZATION_CUTOFF_EVENT } from "./phosphoLocalization";

// The settings alone, plus the session-wide phosphosite localization cutoff:
// both change what a plot shows without changing the page's own settings, so
// both have to rebuild its URL. The mode used to be part of this, so opening or
// closing the panel re-rendered every plot even though nothing about them had changed.
function currentAdvancedPlotSignal(): string {
  return `${getActiveAdvancedPlotSettingsJson()}|localization=${currentLocalizationCutoff()}`;
}

export function useAdvancedPlotSignal(): string {
  const [signal, setSignal] = useState(() => currentAdvancedPlotSignal());

  useEffect(() => {
    const refresh = () => setSignal(currentAdvancedPlotSignal());
    window.addEventListener("copylot:advancedPlotModeChanged", refresh);
    window.addEventListener("copylot:advancedPlotSettingsChanged", refresh);
    window.addEventListener("storage", refresh);
    window.addEventListener(LOCALIZATION_CUTOFF_EVENT, refresh);
    return () => {
      window.removeEventListener(LOCALIZATION_CUTOFF_EVENT, refresh);
      window.removeEventListener("copylot:advancedPlotModeChanged", refresh);
      window.removeEventListener("copylot:advancedPlotSettingsChanged", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  return signal;
}
