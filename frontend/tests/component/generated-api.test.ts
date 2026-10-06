/**
 * src/lib/generated/api.d.ts is exactly what openapi-typescript makes of the
 * committed openapi.json (tests/contracts/test_generated_api_is_current.py
 * checks that openapi.json matches the backend). Regenerate both with
 * `npm run generate:api`.
 */
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import openapiTS, { astToString } from "openapi-typescript";
import { expect, it } from "vitest";

it("the generated types match the committed schema", async () => {
  // vitest runs from frontend/.
  const schema = JSON.parse(await readFile(resolve("src/lib/generated/openapi.json"), "utf8"));
  const committed = await readFile(resolve("src/lib/generated/api.d.ts"), "utf8");
  const generated = astToString(await openapiTS(schema, { defaultNonNullable: false }));
  const body = (text: string) => text.slice(text.indexOf("export interface paths"));
  expect(body(committed)).toBe(body(generated));
}, 30_000);
