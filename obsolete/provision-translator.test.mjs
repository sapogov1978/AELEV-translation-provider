import assert from "node:assert/strict";
import { test } from "node:test";
import { configuration } from "./provision-translator.mjs";

test("generates only a translator-owned URL and preserves existing secret", () => {
  const original = configuration("", "test-ephemeral");
  const again = configuration(original.contents, "ignored-new-secret");
  assert.deepEqual(again, original);
  assert.match(original.contents, /translator_service@|translator_service:/);
});

test("never repurposes another service database", () => {
  assert.throws(() => configuration("AELEV_TRANSLATOR_DATABASE_URL=postgresql+psycopg://crawler:ephemeral@base-screening-postgres/crawler", "unused"));
});
