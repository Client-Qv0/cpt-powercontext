import { test } from "node:test";
import assert from "node:assert/strict";
import { SeekdbClient } from "seekdb";
import { Store } from "../server/store.mjs";

test("real seekdb: increment, refresh, idempotency, isolation, restart, precision guard", async () => {
  const database = `stepfun_test_${Date.now()}`;
  const server = {
    host: process.env.SEEKDB_HOST || "127.0.0.1",
    port: Number(process.env.SEEKDB_PORT || 2881),
    user: process.env.SEEKDB_USER || "root",
    password: process.env.SEEKDB_PASSWORD || "",
  };
  const admin = new SeekdbClient({ ...server, database: "test" });
  await admin.execute(`CREATE DATABASE ${database}`);
  const config = { ...server, database };
  let client = new SeekdbClient(config);
  let store = new Store(client);
  const vector = Array(384).fill(0);
  vector[0] = 1;
  const other = Array(384).fill(0);
  other[1] = 1;
  try {
    await store.create("alpha", "q8");
    await store.create("beta", "q8");
    await store.import("alpha", "q8", [
      {
        id: "one",
        text: "WebGPU speeds browser inference",
        source: "one.txt",
        vector,
      },
    ]);
    await store.import("alpha", "q8", [
      {
        id: "two",
        text: "seekdb refresh makes new vectors searchable",
        source: "two.txt",
        vector: other,
      },
    ]);
    const saved = await store.import("alpha", "q8", [
      {
        id: "one",
        text: "WebGPU speeds browser inference",
        source: "one.txt",
        vector,
      },
    ]);
    assert.equal(saved.count, 2);
    const result = await store.search("alpha", {
      dtype: "q8",
      vector: other,
      text: "refresh",
      k: 2,
    });
    assert.ok(result.hits.some((h) => h.id === "two"));
    assert.equal(
      (await store.search("beta", { dtype: "q8", vector, text: "WebGPU" })).hits
        .length,
      0,
    );
    await assert.rejects(
      store.search("alpha", { dtype: "fp32", vector, text: "WebGPU" }),
      /不一致/,
    );
    await client.close();
    client = new SeekdbClient(config);
    store = new Store(client);
    assert.equal(
      (
        await store.search("alpha", {
          dtype: "q8",
          vector,
          text: "WebGPU",
          k: 1,
        })
      ).hits[0].id,
      "one",
    );
  } finally {
    await client.close();
    await admin.execute(`DROP DATABASE ${database}`);
    await admin.close();
  }
});
