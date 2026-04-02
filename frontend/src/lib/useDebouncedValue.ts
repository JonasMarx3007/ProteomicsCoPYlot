import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delayMs = 600): T {
  const [debounced, setDebounced] = useState<T>(value);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      setDebounced(value);
    }, Math.max(0, delayMs));

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [value, delayMs]);

  return debounced;
}

