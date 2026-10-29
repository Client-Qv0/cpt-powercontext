import { mkdir, readFile, writeFile, rename } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { MODEL, REVISION } from "../src/config.js";

const root = new URL("../public/models/", import.meta.url);
const expected = JSON.parse(
  await readFile(
    new URL("../data/model-manifest.json", import.meta.url),
    "utf8",
  ),
);
const files = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "special_tokens_map.json",
  "onnx/model.onnx",
  "onnx/model_quantized.onnx",
];
const manifest = { model: MODEL, revision: REVISION, files: [] };
for (const file of files) {
  const dest = new URL(`${MODEL}/${file}`, root);
  await mkdir(path.dirname(fileURLToPath(dest)), { recursive: true });
  let data;
  const matches = (buffer) => {
    const entry = expected.files.find((f) => f.file === file);
    return (
      buffer.length === entry.bytes &&
      createHash("sha256").update(buffer).digest("hex") === entry.sha256
    );
  };
  try {
    data = await readFile(dest);
    if (!matches(data)) throw new Error("invalid cached file");
  } catch {
    const url = `${process.env.HF_ENDPOINT || "https://huggingface.co"}/${MODEL}/resolve/${REVISION}/${file}?download=true`;
    console.log(`Downloading ${file}`);
    const response = await fetch(url, { signal: AbortSignal.timeout(300_000) });
    if (!response.ok) throw new Error(`${file}: HTTP ${response.status}`);
    data = Buffer.from(await response.arrayBuffer());
    if (!matches(data)) throw new Error(`${file}: 与固定版本的 SHA-256 不符`);
    if (file.endsWith(".json")) JSON.parse(data.toString("utf8"));
    const temp = new URL(`${MODEL}/${file}.partial`, root);
    await writeFile(temp, data);
    await rename(temp, dest);
  }
  manifest.files.push({
    file,
    bytes: data.length,
    sha256: createHash("sha256").update(data).digest("hex"),
  });
}
const shared = manifest.files
  .filter((f) => !f.file.endsWith(".onnx"))
  .reduce((s, f) => s + f.bytes, 0);
manifest.fp32Bytes =
  shared + manifest.files.find((f) => f.file === "onnx/model.onnx").bytes;
manifest.q8Bytes =
  shared +
  manifest.files.find((f) => f.file === "onnx/model_quantized.onnx").bytes;
manifest.compressionRatio = manifest.fp32Bytes / manifest.q8Bytes;
await writeFile(
  new URL("manifest.json", root),
  JSON.stringify(manifest, null, 2),
);
console.log(JSON.stringify(manifest, null, 2));
