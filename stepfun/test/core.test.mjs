import { test } from "node:test";
import assert from "node:assert/strict";
import { chunks, recallAtK, ndcgAtK, median } from "../src/text.js";
import { validateVector, validateName } from "../server/store.mjs";

test("chunking preserves the final text and the overlap", () => {
  const text = "abcde".repeat(260);
  const parts = chunks(text);
  assert.equal(parts[0].length, 600);
  assert.equal(parts[0].slice(-80), parts[1].slice(0, 80));
  assert.equal(parts[2].slice(-40), text.slice(-40));
  assert.deepEqual(chunks("   "), []);
});
test("quality metrics penalize missing relevant documents and rank order", () => {
  assert.equal(recallAtK(["b", "x", "a"], ["a", "b"], 2), 0.5);
  assert.equal(ndcgAtK(["a", "b"], ["a", "b"]), 1);
  assert.ok(ndcgAtK(["x", "a"], ["a"]) < 1);
  assert.equal(median([5, 1, 3, 9]), 4);
});
test("reject incompatible, invalid and unsafe input before touching the database", () => {
  for (const v of [
    [],
    Array(384).fill(0),
    Array(384).fill(NaN),
    Array(384).fill("1"),
  ])
    assert.throws(() => validateVector(v));
  validateVector(Array(384).fill(0.01));
  for (const name of ["../../x", "other; DROP TABLE a", "", "X"])
    assert.throws(() => validateName(name));
  assert.equal(validateName("notes_1"), "stepfun_notes_1");
});
