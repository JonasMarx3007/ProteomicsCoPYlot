import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/lib/accessTokens.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { fragmentCredential, removeCredentialQuery } = await import(moduleUrl);

test("named fragments carry access credentials", () => {
  assert.equal(fragmentCredential("#tool=secret", ["tool", "toolToken"]), "secret");
  assert.equal(fragmentCredential("#section", ["tool", "toolToken"]), "");
});

test("query credentials are ignored and removed", () => {
  const href = "https://example.test/viewer/?qr=leaked&tab=qc#section";
  assert.equal(fragmentCredential(new URL(href).hash, ["qr", "qrToken"]), "");
  assert.equal(
    removeCredentialQuery(href, ["qr", "qrToken"]),
    "/viewer/?tab=qc#section",
  );
});
