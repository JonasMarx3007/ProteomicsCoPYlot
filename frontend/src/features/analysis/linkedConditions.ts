/**
 * The linked volcano's two conditions as the `conditions` query parameter.
 *
 * A JSON list, never a comma-joined string: a condition may itself contain a
 * comma ("Drug, high"), and the plot routes split a plain string at every one,
 * so that condition used to drop out of the plot without a word.
 */
export function linkedConditionsParam(
  settings: { condition1?: string | null; condition2?: string | null } | null | undefined
): string {
  if (!settings) return "[]";
  return JSON.stringify([settings.condition1 ?? "", settings.condition2 ?? ""].filter(Boolean));
}
