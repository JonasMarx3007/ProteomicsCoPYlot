/**
 * Access credentials travel in the URL fragment, never in the query string.
 *
 * A fragment is not sent to the server or written to its logs; a query string
 * is. A credential that arrives in the query is therefore ignored and stripped
 * from the address bar rather than honoured.
 *
 * Converted from a node --test file that transpiled the module by hand.
 */
import { expect, it } from "vitest";
import { fragmentCredential, removeCredentialQuery } from "../../src/lib/accessTokens";

it("named fragments carry access credentials", () => {
  expect(fragmentCredential("#tool=secret", ["tool", "toolToken"])).toBe("secret");
  expect(fragmentCredential("#section", ["tool", "toolToken"])).toBe("");
});

it("query credentials are ignored and removed", () => {
  const href = "https://example.test/viewer/?qr=leaked&tab=qc#section";
  expect(fragmentCredential(new URL(href).hash, ["qr", "qrToken"])).toBe("");
  expect(removeCredentialQuery(href, ["qr", "qrToken"])).toBe("/viewer/?tab=qc#section");
});
