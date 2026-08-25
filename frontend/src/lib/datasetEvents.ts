import type { CurrentDatasetsResponse } from "./types";

const DATASET_STATE_CHANGED_EVENT = "copylot:dataset-state-changed";

export function emitDatasetStateChanged(snapshot?: CurrentDatasetsResponse): void {
  window.dispatchEvent(
    new CustomEvent<CurrentDatasetsResponse | undefined>(DATASET_STATE_CHANGED_EVENT, {
      detail: snapshot,
    })
  );
}

export function subscribeDatasetStateChanged(
  handler: (snapshot?: CurrentDatasetsResponse) => void
): () => void {
  const listener: EventListener = (event) => {
    const snapshot =
      event instanceof CustomEvent
        ? (event.detail as CurrentDatasetsResponse | undefined)
        : undefined;
    handler(snapshot);
  };
  window.addEventListener(DATASET_STATE_CHANGED_EVENT, listener);
  return () => {
    window.removeEventListener(DATASET_STATE_CHANGED_EVENT, listener);
  };
}
