import { useCallback, useRef, useState } from "react";

import { resolveDataSource, savedDataSource, type DataSource, type DataSourceChoices } from "./types";

/**
 * A panel's data-source selection: the served default until the user chooses.
 *
 * The rule is "open on the most processed matrix available, but never overrule a
 * deliberate choice". Those two pull in opposite directions, and the difference
 * between them is entirely whether a choice has been made -- which is why a
 * panel must not invent one. Initialising the state to `"data"` before the
 * backend has answered looks exactly like a user who picked Data: `"data"` is
 * always available, so `resolveDataSource` keeps it, and the default never
 * applies. Every selector opened on Data for that reason, on projects whose
 * backend was reporting `defaultDataSource: "imputed"`.
 *
 * So the saved choice is read once, kept as null when there is none, and the
 * ladder default is taken exactly once -- the first time the backend says which
 * matrices exist.
 */
export function useDataSourceChoice(persisted: unknown): {
  dataSource: DataSource;
  /** A saved choice existed, or the backend has said which matrices exist.
   * Until then `dataSource` is the placeholder and must not be requested. */
  ready: boolean;
  applyChoices: (choices: Partial<DataSourceChoices> | null | undefined) => void;
  chooseDataSource: (value: DataSource) => void;
} {
  const [initial] = useState(() => savedDataSource(persisted));
  const chosen = useRef(initial !== null);
  // "data" is a placeholder only while `chosen` is false; nothing reads it
  // before the options arrive, because every request is gated on them.
  const [dataSource, setDataSource] = useState<DataSource>(initial ?? "data");
  const [ready, setReady] = useState(initial !== null);

  const applyChoices = useCallback(
    (choices: Partial<DataSourceChoices> | null | undefined) => {
      // Read and flip the ref here, not inside the updater: React StrictMode
      // invokes an updater twice from the same base state, so a ref flipped
      // inside it makes the second pass take the other branch and throw the
      // default away.
      const takeDefault = !chosen.current;
      chosen.current = true;
      setReady(true);
      setDataSource((current) =>
        takeDefault
          ? choices?.defaultDataSource ?? resolveDataSource(current, choices)
          // From here on a still-valid choice survives, and only a matrix that
          // has gone away falls back to the default.
          : resolveDataSource(current, choices)
      );
    },
    []
  );

  const chooseDataSource = useCallback((value: DataSource) => {
    chosen.current = true;
    setReady(true);
    setDataSource(value);
  }, []);

  return { dataSource, ready, applyChoices, chooseDataSource };
}
