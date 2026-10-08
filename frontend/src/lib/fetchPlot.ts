function retryDelay(response: Response): number | null {
  const value = response.headers.get("Retry-After");
  if (response.status !== 503 || !value?.trim()) return null;
  const delay = /^\d+$/.test(value.trim()) ? Number(value) * 1000
    : /^[A-Za-z]{3}, /.test(value.trim()) ? Date.parse(value) - Date.now() : NaN;
  // Never retry earlier than requested; long outages should surface normally.
  return Number.isFinite(delay) && delay <= 10_000 ? Math.max(1000, delay) : null;
}

function waitForRetry(delay: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted();
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, delay);
    signal.addEventListener("abort", abort, { once: true });
  });
}

/** Retry only explicitly temporary, read-only plot requests; never replay writes. */
export async function fetchPlot(url: string, signal: AbortSignal, headers?: Record<string, string>): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    signal.throwIfAborted();
    const response = await fetch(url, headers ? { signal, headers } : { signal });
    const delay = retryDelay(response);
    if (delay === null || attempt >= 3) return response;
    await response.body?.cancel();
    await waitForRetry(delay, signal);
  }
}
