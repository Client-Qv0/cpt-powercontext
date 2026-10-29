import {
  SeekdbClient,
  Schema,
  VectorIndexConfig,
  FulltextIndexConfig,
} from "seekdb";
import { DIMENSION, PRECISIONS, signature } from "../src/config.js";

export function databaseClient() {
  return new SeekdbClient({
    host: process.env.SEEKDB_HOST || "127.0.0.1",
    port: Number(process.env.SEEKDB_PORT || 2881),
    user: process.env.SEEKDB_USER || "root",
    password: process.env.SEEKDB_PASSWORD || "",
    database: process.env.SEEKDB_DATABASE || "test",
  });
}
export class InputError extends Error {}
export function validateVector(vector) {
  if (
    !Array.isArray(vector) ||
    vector.length !== DIMENSION ||
    vector.some((v) => typeof v !== "number" || !Number.isFinite(v)) ||
    !vector.some((v) => v !== 0)
  )
    throw new InputError("需要浏览器生成的 384 维非零有限数值向量");
}
export function validateName(name) {
  if (typeof name !== "string" || !/^[a-z][a-z0-9_]{0,39}$/.test(name)) {
    throw new InputError(
      "知识库名须为小写字母开头，最多 40 位字母、数字或下划线",
    );
  }
  return `stepfun_${name}`;
}

export class Store {
  constructor(client) {
    this.client = client;
    this.queues = new Map();
  }
  async catalog() {
    if (!this.catalogReady)
      this.catalogReady = this.client
        .execute(
          "CREATE TABLE IF NOT EXISTS stepfun_catalog (name VARCHAR(40) PRIMARY KEY, dtype VARCHAR(8) NOT NULL, model_signature VARCHAR(255) NOT NULL)",
        )
        .catch((error) => {
          this.catalogReady = null;
          throw error;
        });
    await this.catalogReady;
  }
  // A refresh and its writes form one visibility boundary, also across concurrent tabs.
  async locked(name, fn) {
    const previous = this.queues.get(name) || Promise.resolve();
    const next = previous.catch(() => {}).then(fn);
    this.queues.set(name, next);
    try {
      return await next;
    } finally {
      if (this.queues.get(name) === next) this.queues.delete(name);
    }
  }
  async list() {
    await this.catalog();
    return await this.client.execute(
      "SELECT name, dtype FROM stepfun_catalog ORDER BY name",
    );
  }
  async collection(name, dtype, create = false) {
    const dbName = validateName(name);
    if (!PRECISIONS.includes(dtype))
      throw new InputError("精度必须为 q8 或 fp32");
    await this.catalog();
    const entries = await this.client.execute(
      "SELECT model_signature FROM stepfun_catalog WHERE name = ?",
      [name],
    );
    if (!entries?.length && !create)
      throw new InputError("知识库不存在，请先创建");
    if (entries?.length && entries[0].model_signature !== signature(dtype)) {
      throw new InputError(
        "知识库模型/精度不一致，请切换到匹配的精度或新建知识库",
      );
    }
    if (entries?.length)
      return this.client.getCollection({
        name: dbName,
        embeddingFunction: null,
      });
    const c = await this.client.createCollection({
      name: dbName,
      schema: new Schema({
        vectorIndex: new VectorIndexConfig({
          hnsw: { dimension: DIMENSION, distance: "cosine" },
          embeddingFunction: null,
        }),
        fulltextIndex: new FulltextIndexConfig("beng"),
      }),
    });
    await this.client.execute(
      "INSERT INTO stepfun_catalog (name, dtype, model_signature) VALUES (?, ?, ?)",
      [name, dtype, signature(dtype)],
    );
    return c;
  }
  async create(name, dtype) {
    return this.locked(name, async () => {
      const c = await this.collection(name, dtype, true);
      return { count: await c.count() };
    });
  }
  async import(name, dtype, records, refreshEach = false) {
    if (!Array.isArray(records) || !records.length || records.length > 256)
      throw new InputError("每次导入 1–256 个分块");
    const seen = new Set();
    for (const r of records) {
      if (
        typeof r.id !== "string" ||
        !/^[a-zA-Z0-9_-]{1,128}$/.test(r.id) ||
        seen.has(r.id) ||
        typeof r.text !== "string" ||
        !r.text.trim() ||
        r.text.length > 4000 ||
        typeof r.source !== "string" ||
        r.source.length > 256
      )
        throw new InputError("无效的文档 ID、原文或来源");
      seen.add(r.id);
      validateVector(r.vector);
    }
    return this.locked(name, async () => {
      const c = await this.collection(name, dtype);
      const start = performance.now();
      let refreshMs = 0;
      for (const batch of refreshEach ? records.map((r) => [r]) : [records]) {
        await c.upsert({
          ids: batch.map((r) => r.id),
          documents: batch.map((r) => r.text),
          embeddings: batch.map((r) => r.vector),
          metadatas: batch.map((r) => ({ source: r.source, dtype })),
        });
        const t = performance.now();
        await c.refresh_index();
        refreshMs += performance.now() - t;
      }
      return {
        count: await c.count(),
        writeMs: performance.now() - start - refreshMs,
        refreshMs,
      };
    });
  }
  async search(name, { dtype, vector, text, mode = "hybrid", k = 5 }) {
    validateVector(vector);
    if (
      typeof text !== "string" ||
      !text.trim() ||
      text.length > 1000 ||
      !["hybrid", "vector"].includes(mode) ||
      !Number.isInteger(k) ||
      k < 1 ||
      k > 20
    )
      throw new InputError("无效的查询");
    return this.locked(name, async () => {
      const c = await this.collection(name, dtype);
      const start = performance.now();
      // Both candidate generation and RRF ranking execute in seekdb, never in the browser.
      const result =
        mode === "hybrid"
          ? await c.hybridSearch({
              query: {
                whereDocument: { $contains: text },
                nResults: Math.max(20, k),
              },
              knn: { queryEmbeddings: [vector], nResults: Math.max(20, k) },
              rank: { rrf: {} },
              nResults: k,
              include: ["documents", "metadatas", "distances"],
            })
          : await c.query({
              queryEmbeddings: [vector],
              nResults: k,
              include: ["documents", "metadatas", "distances"],
            });
      return {
        searchMs: performance.now() - start,
        hits: (result.ids[0] || []).map((id, i) => ({
          id,
          text: result.documents?.[0]?.[i],
          metadata: result.metadatas?.[0]?.[i],
          distance: result.distances?.[0]?.[i],
        })),
      };
    });
  }
}
