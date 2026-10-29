import { pipeline, env } from "@huggingface/transformers";
import { MODEL, REVISION } from "./config.js";
import wasmURL from "../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.wasm?url";
import wasmFactoryURL from "../node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.asyncify.mjs?url";
env.allowLocalModels = true;
env.localModelPath = "/models/";
env.backends.onnx.wasm.numThreads = 1;
// Serve the matching ORT factory and binary locally, including in an offline build.
env.backends.onnx.wasm.wasmPaths = { wasm: wasmURL, mjs: wasmFactoryURL };
let extractor, current, backend, fallback;

async function load(dtype, forceWasm) {
  const key = `${dtype}:${forceWasm}`;
  if (extractor && current === key) return;
  if (extractor) {
    await extractor.dispose();
    extractor = null;
  }
  fallback = "";
  const options = {
    dtype,
    revision: REVISION,
    progress_callback: (progress) => postMessage({ progress }),
  };
  if (!forceWasm && navigator.gpu) {
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (!adapter) throw new Error("无可用 WebGPU adapter");
      extractor = await pipeline("feature-extraction", MODEL, {
        ...options,
        device: "webgpu",
      });
      backend = "WebGPU";
    } catch (error) {
      fallback = `WebGPU 初始化失败：${error.message}`;
    }
  } else {
    fallback = forceWasm ? "已选择强制 WASM 验证" : "浏览器未提供 WebGPU";
  }
  if (!extractor) {
    extractor = await pipeline("feature-extraction", MODEL, {
      ...options,
      device: "wasm",
    });
    backend = "WASM";
  }
  current = key;
}
let queue = Promise.resolve();
self.onmessage = ({ data }) => {
  queue = queue
    .catch(() => {})
    .then(async () => {
      const {
        id,
        texts,
        dtype = "q8",
        forceWasm = false,
        batchSize = 8,
      } = data;
      try {
        const loadStart = performance.now();
        await load(dtype, forceWasm);
        const loadMs = performance.now() - loadStart;
        const start = performance.now(),
          vectors = [];
        for (let i = 0; i < texts.length; i += batchSize) {
          const output = await extractor(texts.slice(i, i + batchSize), {
            pooling: "mean",
            normalize: true,
          });
          vectors.push(...output.tolist());
          postMessage({
            completed: Math.min(i + batchSize, texts.length),
            total: texts.length,
          });
        }
        postMessage({
          id,
          vectors,
          loadMs,
          embedMs: performance.now() - start,
          backend,
          fallback,
        });
      } catch (error) {
        postMessage({ id, error: error.message });
      }
    });
};
