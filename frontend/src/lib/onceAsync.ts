export function onceAsync(action: () => Promise<void>): () => Promise<void> {
  let pending: Promise<void> | undefined;
  // Retain failures too: consumers must not silently read pre-reset state.
  return () => pending ??= Promise.resolve().then(action);
}
