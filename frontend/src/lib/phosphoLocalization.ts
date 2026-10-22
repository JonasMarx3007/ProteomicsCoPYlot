import { useCallback, useEffect, useState } from "react";
import { getPhosphoLocalizationCutoff, setPhosphoLocalizationCutoff } from "./api";
import { subscribeDatasetStateChanged } from "./datasetEvents";

// One shared value for the whole session (see backend services/phospho_localization.py).
// Every field that shows it reads this store, so changing it on one page
// changes it on every page.
type State = { cutoff: number; available: boolean; loaded: boolean; belowClassOne: number; sites: number };

let state: State = { cutoff: 0, available: false, loaded: false, belowClassOne: 0, sites: 0 };
const listeners = new Set<(next: State) => void>();

export const LOCALIZATION_CUTOFF_EVENT = "copylot:phospho-localization-cutoff-changed";

export function currentLocalizationCutoff(): number {
  return state.cutoff;
}

function publish(next: State) {
  const changed = next.cutoff !== state.cutoff;
  state = next;
  listeners.forEach((listener) => listener(state));
  // Plot URLs are memoized on each page's own settings; this event is what
  // makes them rebuild (see useAdvancedPlotSignal).
  if (changed) window.dispatchEvent(new Event(LOCALIZATION_CUTOFF_EVENT));
}

async function refresh() {
  try {
    const current = await getPhosphoLocalizationCutoff();
    publish({ cutoff: current.cutoff, available: current.available, loaded: true, belowClassOne: current.belowClassOne ?? 0, sites: current.sites ?? 0 });
  } catch {
    publish({ ...state, loaded: true });
  }
}

let subscribed = false;

function ensureSubscribed() {
  if (subscribed) return;
  subscribed = true;
  // A new dataset, a restore or a session reset can change both the value and
  // whether the loaded phosphosite table has a localization column.
  subscribeDatasetStateChanged(() => void refresh());
}

export function usePhosphoLocalizationCutoff() {
  const [current, setCurrent] = useState<State>(state);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listeners.add(setCurrent);
    ensureSubscribed();
    if (!state.loaded) void refresh();
    return () => {
      listeners.delete(setCurrent);
    };
  }, []);

  const update = useCallback(async (cutoff: number) => {
    setError(null);
    try {
      const next = await setPhosphoLocalizationCutoff(cutoff);
      publish({ cutoff: next.cutoff, available: next.available, loaded: true, belowClassOne: next.belowClassOne ?? 0, sites: next.sites ?? 0 });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to set the localization probability cutoff");
    }
  }, []);

  return { cutoff: current.cutoff, available: current.available, loaded: current.loaded, belowClassOne: current.belowClassOne, sites: current.sites, error, update };
}
