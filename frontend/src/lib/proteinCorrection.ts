import { useEffect, useMemo, useState } from "react";
import type { AnnotationKind, DataSource, ProteinCorrectionOptions } from "./types";
import { dataSourceOptions, DATA_SOURCE_LABELS } from "./types";

export const PROTEIN_CORRECTION_LABEL = "Correct site changes for protein abundance";

/** The protein-correction choice of a phosphosite statistics panel.
 *
 * Offered only for phosphosites and only when the backend reports a protein
 * dataset in the package (`options.proteinCorrection.available`). While it is
 * on, the data-source selector is narrowed to the matrices both datasets hold,
 * because the correction mirrors the site comparison's source on the protein
 * side rather than substituting another one; a choice outside that set moves
 * to the first shared one. `active` is what the requests send. */
export function useProteinCorrection(
  kind: AnnotationKind,
  options: { proteinCorrection?: ProteinCorrectionOptions | null; availableDataSources?: DataSource[] } | null,
  persisted: unknown,
  dataSource: DataSource,
  chooseDataSource: (value: DataSource) => void,
  /** False on a page whose current view does not run a site comparison (the
   * choice is kept but neither offered nor applied). */
  relevant: boolean = true,
): {
  enabled: boolean;
  setEnabled: (value: boolean) => void;
  offered: boolean;
  active: boolean;
  dataSourceOptions: { value: DataSource; label: string }[];
} {
  const [enabled, setEnabled] = useState(() => Boolean(persisted));
  const offered = relevant && kind === "phospho" && Boolean(options?.proteinCorrection?.available);
  const active = offered && enabled;
  const shared = useMemo(
    () => (options?.proteinCorrection?.dataSources ?? []) as DataSource[],
    [options],
  );
  const sourceOptions = useMemo(
    () => (active && shared.length
      ? shared.map((value) => ({ value, label: DATA_SOURCE_LABELS[value] }))
      : dataSourceOptions(options)),
    [active, shared, options],
  );
  useEffect(() => {
    if (active && shared.length && !shared.includes(dataSource)) chooseDataSource(shared[0]);
  }, [active, shared, dataSource, chooseDataSource]);
  return { enabled, setEnabled, offered, active, dataSourceOptions: sourceOptions };
}
