const DATASET_STATE_CHANGED_EVENT = "copylot:dataset-state-changed";

export function emitDatasetStateChanged(): void {
  window.dispatchEvent(new CustomEvent(DATASET_STATE_CHANGED_EVENT));
}

export function subscribeDatasetStateChanged(handler: () => void): () => void {
  const listener = () => handler();
  window.addEventListener(DATASET_STATE_CHANGED_EVENT, listener);
  return () => {
    window.removeEventListener(DATASET_STATE_CHANGED_EVENT, listener);
  };
}
