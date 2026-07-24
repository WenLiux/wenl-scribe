import assert from "node:assert/strict";
import test from "node:test";
import { BRAND_COPY } from "../app/brand.ts";

test("keeps the WENL brand slogan in one source of truth", () => {
  assert.equal(BRAND_COPY.name, "留文");
  assert.equal(BRAND_COPY.slogan, "所见所听，皆可留文");
});
