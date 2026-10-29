import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { databaseClient, Store, InputError } from "./store.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
process.chdir(root);
process.env.SEEKDB_BINDINGS_CACHE_DIR ||= path.join(
  root,
  ".seekdb",
  "bindings",
);
const client = databaseClient();
const store = new Store(client);
const app = express();
app.use(express.json({ limit: "8mb" }));
// Local application: do not expose the API to arbitrary web origins.
app.use("/api", (req, res, next) => {
  if (
    req.headers.origin &&
    req.headers.origin !== `${req.protocol}://${req.headers.host}`
  ) {
    return res.status(403).json({ error: "仅接受同源请求" });
  }
  next();
});
app.get("/api/collections", async (_req, res) => res.json(await store.list()));
app.post("/api/collections", async (req, res) =>
  res.json(await store.create(req.body.name, req.body.dtype)),
);
app.post("/api/collections/:name/import", async (req, res) =>
  res.json(
    await store.import(
      req.params.name,
      req.body.dtype,
      req.body.records,
      req.body.refreshEach === true,
    ),
  ),
);
app.post("/api/collections/:name/search", async (req, res) =>
  res.json(await store.search(req.params.name, req.body)),
);
app.use("/api", (_req, res) => res.status(404).json({ error: "接口不存在" }));
app.use((err, _req, res, _next) => {
  console.error(err.message);
  res
    .status(
      err instanceof InputError || err.type === "entity.parse.failed"
        ? 400
        : 503,
    )
    .json({ error: err.message });
});
if (process.argv.includes("--production")) {
  app.use(express.static(path.join(root, "dist")));
} else {
  const { createServer } = await import("vite");
  const vite = await createServer({
    root,
    server: { middlewareMode: true },
    appType: "spa",
  });
  app.use(vite.middlewares);
}
const port = Number(process.env.PORT || 5173);
const server = app.listen(port, "127.0.0.1", () =>
  console.log(`Knowledge Lab: http://localhost:${port}`),
);
process.on("SIGINT", () =>
  server.close(async () => {
    await client.close();
    process.exit(0);
  }),
);
