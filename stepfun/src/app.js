import "./style.css";
import { MODEL, REVISION } from "./config.js";
import { chunks, recallAtK, ndcgAtK, median } from "./text.js";
import dataset from "../data/evaluation.json";

document.querySelector("#app").innerHTML = `
<header><span class="logo">K<span>↗</span></span><div><b>Knowledge Lab</b><small>浏览器本地推理 · seekdb 混合检索</small></div><span class="pill" id="backend">模型尚未加载</span></header>
<main><section class="intro"><p class="eyebrow">SEEKDB × STEPFUN / EDGE AI</p><h1>知识留在手边。<br><span>答案从原文中来。</span></h1><p>导入文本，在当前设备生成向量，由 seekdb 完成语义与全文混合检索。</p></section>
<div class="layout"><aside><section class="card"><h2>01 / 知识库</h2><label>当前知识库<select id="collections"><option value="">请选择或新建</option></select></label><label>新建名称<input id="name" placeholder="例如 research_notes" maxlength="40"></label><label>模型精度<select id="dtype"><option value="q8">INT8 · 推荐</option><option value="fp32">FP32 · 对照基线</option></select></label><label class="check"><input id="wasm" type="checkbox">强制 WASM（验证降级）</label><button id="create">创建 / 打开知识库</button><p class="muted">MiniLM-L6-v2 · 384 维 · mean pooling · 归一化<br>知识库绑定模型版本及精度，避免混用向量。</p></section>
<section class="card"><h2>02 / 导入语料</h2><label class="drop">选择 TXT / Markdown 文件<input id="files" type="file" accept=".txt,.md,text/plain,text/markdown" multiple></label><label>或粘贴文档<textarea id="document" rows="5" placeholder="粘贴需要检索的原文…"></textarea></label><button id="import">本地向量化并导入</button><button class="secondary" id="sample">导入示例语料</button><progress id="progress" max="100" value="0"></progress><p id="status" role="status">准备就绪</p></section></aside>
<article><section class="card search"><h2>03 / 检索原文</h2><form id="search"><input id="query" placeholder="输入问题，例如：How does WebGPU accelerate inference?" required><div class="row"><select id="mode"><option value="hybrid">混合检索 · seekdb RRF</option><option value="vector">仅向量检索</option></select><button>检索</button></div></form><div id="timing" class="muted"></div></section><section id="results" aria-live="polite"><div class="empty"><span>⌕</span><h3>让你的文档成为答案</h3><p>创建知识库、导入语料，然后输入查询。<br>检索结果将展示排序和对应原文。</p></div></section>
<section class="card"><div class="row"><h2>实验台 / 可复现评测</h2><button class="secondary" id="benchmark">运行完整评测</button><button class="secondary" id="export">导出原始 JSON</button></div><p class="muted">固定 12 篇英文语料、6 条查询；对比 FP32 / INT8、单条 / 批量、逐条 / 批次刷新。每条查询运行 3 次，报告 Recall@3、nDCG@3 和中位数。首次模型下载可能需要数分钟。</p><div id="report">尚未运行评测。</div></section></article></div><footer>计算发生在当前浏览器 Worker · 原文与向量仅发送到本地 seekdb 网关 · 模型：${MODEL}</footer></main>`;

const $ = (id) => document.getElementById(id);
const worker = new Worker(new URL("./embedding.worker.js", import.meta.url), {
  type: "module",
});
let requestId = 0,
  active = "",
  busy = false,
  lastReport;
const pending = new Map();
worker.onmessage = ({ data }) => {
  if (data.progress) {
    const p = data.progress;
    $("status").textContent =
      `模型 ${p.status} ${p.file || ""} ${Math.round(p.progress || 0)}%`;
  }
  if (data.completed) {
    $("progress").value = (data.completed / data.total) * 100;
    $("status").textContent = `向量化 ${data.completed} / ${data.total}`;
  }
  if (data.id) {
    const handlers = pending.get(data.id);
    pending.delete(data.id);
    if (data.error) handlers.reject(new Error(data.error));
    else {
      $("backend").textContent =
        `${data.backend} · ${data.fallback || "GPU 优先"} `;
      handlers.resolve(data);
    }
  }
};
worker.onerror = (event) => {
  for (const p of pending.values()) p.reject(new Error(event.message));
  pending.clear();
};
function embed(texts, options = {}) {
  const id = ++requestId;
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    worker.postMessage({
      id,
      texts,
      dtype: $("dtype").value,
      forceWasm: $("wasm").checked,
      batchSize: 8,
      ...options,
    });
  });
}
async function api(path, body) {
  const response = await fetch(
    `/api/${path}`,
    body === undefined
      ? { signal: AbortSignal.timeout(300_000) }
      : {
          signal: AbortSignal.timeout(300_000),
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}
function node(tag, text, className = "") {
  const el = document.createElement(tag);
  el.textContent = text;
  el.className = className;
  return el;
}
async function run(fn) {
  if (busy) return;
  busy = true;
  document
    .querySelectorAll("button,select,input,textarea")
    .forEach((el) => (el.disabled = true));
  $("status").className = "";
  $("progress").value = 0;
  try {
    await fn();
  } catch (error) {
    $("status").textContent = error.message;
    $("status").className = "error";
  } finally {
    busy = false;
    document
      .querySelectorAll("button,select,input,textarea")
      .forEach((el) => (el.disabled = false));
  }
}
async function list() {
  const all = await api("collections");
  $("collections").replaceChildren(
    new Option("请选择或新建", ""),
    ...all.map((c) => new Option(`${c.name} · ${c.dtype}`, c.name)),
  );
  $("collections").value = active;
  return all;
}
function requireActive() {
  if (!active) throw new Error("请先创建或选择知识库");
  return active;
}
$("create").onclick = () =>
  run(async () => {
    const name = $("name").value.trim();
    const result = await api("collections", { name, dtype: $("dtype").value });
    active = name;
    localStorage.setItem("stepfun-active", name);
    await list();
    $("status").textContent = `${name} 已打开，共 ${result.count} 个分块`;
    $("results").replaceChildren();
    $("timing").textContent = "";
  });
$("collections").onchange = () =>
  run(async () => {
    active = $("collections").value;
    localStorage.setItem("stepfun-active", active);
    const all = await list(),
      current = all.find((c) => c.name === active);
    if (current) $("dtype").value = current.dtype;
    $("results").replaceChildren();
    $("timing").textContent = "";
    $("status").textContent = active ? `当前知识库：${active}` : "请选择知识库";
  });
$("dtype").onchange = () => {
  $("status").textContent = "精度改变后请选择匹配的知识库，或新建知识库。";
};
async function importDocs(docs) {
  const name = requireActive(),
    dtype = $("dtype").value;
  const records = [];
  for (const doc of docs) {
    for (const [i, text] of chunks(doc.text).entries()) {
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(`${doc.id || doc.source}:${i}:${text}`),
      );
      records.push({
        id: Array.from(new Uint8Array(digest), (n) =>
          n.toString(16).padStart(2, "0"),
        ).join(""),
        text,
        source: doc.source,
      });
    }
  }
  if (!records.length || records.length > 256)
    throw new Error("请导入 1–256 个分块（每块最多 600 字符）");
  const result = await embed(records.map((r) => r.text));
  records.forEach((r, i) => (r.vector = result.vectors[i]));
  $("status").textContent = "写入 seekdb 并刷新索引…";
  const saved = await api(`collections/${name}/import`, { dtype, records });
  $("status").textContent =
    `已就绪：${saved.count} 个分块 · 模型加载 ${result.loadMs.toFixed(0)}ms · 向量化 ${result.embedMs.toFixed(0)}ms · 写入 ${saved.writeMs.toFixed(0)}ms · 刷新 ${saved.refreshMs.toFixed(0)}ms`;
}
$("import").onclick = () =>
  run(async () => {
    const docs = [];
    for (const file of $("files").files) {
      if (file.size > 1024 * 1024) throw new Error("单个文件最多 1 MiB");
      docs.push({ source: file.name, text: await file.text() });
    }
    if ($("document").value.trim())
      docs.push({ source: "粘贴文档", text: $("document").value });
    await importDocs(docs);
  });
$("sample").onclick = () =>
  run(() => importDocs(dataset.documents.map((d) => ({ ...d, source: d.id }))));
$("search").onsubmit = (event) => {
  event.preventDefault();
  run(async () => {
    const name = requireActive(),
      text = $("query").value.trim(),
      start = performance.now();
    const encoded = await embed([text]);
    const result = await api(`collections/${name}/search`, {
      text,
      vector: encoded.vectors[0],
      dtype: $("dtype").value,
      mode: $("mode").value,
      k: 5,
    });
    $("results").replaceChildren();
    for (const [i, hit] of result.hits.entries()) {
      const card = node("section", "", "card hit");
      card.append(
        node("small", `#${i + 1} · ${hit.metadata?.source || hit.id}`),
        node("p", hit.text),
      );
      $("results").append(card);
    }
    if (!result.hits.length)
      $("results").append(node("p", "当前知识库没有匹配结果。"));
    $("timing").textContent =
      `查询向量化 ${encoded.embedMs.toFixed(1)}ms · seekdb ${result.searchMs.toFixed(1)}ms · 端到端 ${(performance.now() - start).toFixed(1)}ms`;
    $("status").textContent = `检索完成，${result.hits.length} 条结果`;
  });
};

async function benchmark() {
  const report = {
    timestamp: new Date().toISOString(),
    userAgent: navigator.userAgent,
    runtime: "Transformers.js 4.3.2",
    hardwareConcurrency: navigator.hardwareConcurrency,
    model: MODEL,
    revision: REVISION,
    corpusSize: dataset.documents.length,
    queryCount: dataset.queries.length,
    k: 3,
    runs: [],
  };
  try {
    report.modelFiles = await (await fetch("/models/manifest.json")).json();
  } catch {
    report.modelFiles = null;
  }
  const configs = [
    {
      name: "FP32 / WASM / batch1 / refresh1",
      dtype: "fp32",
      forceWasm: true,
      batchSize: 1,
      refreshEach: true,
    },
    {
      name: "INT8 / WASM / batch1 / refresh1",
      dtype: "q8",
      forceWasm: true,
      batchSize: 1,
      refreshEach: true,
    },
    {
      name: "INT8 / WASM / batch8 / refresh1",
      dtype: "q8",
      forceWasm: true,
      batchSize: 8,
      refreshEach: true,
    },
    {
      name: "INT8 / WASM / batch8 / refreshBatch",
      dtype: "q8",
      forceWasm: true,
      batchSize: 8,
      refreshEach: false,
    },
    {
      name: "INT8 / GPU优先 / batch8 / refreshBatch",
      dtype: "q8",
      forceWasm: false,
      batchSize: 8,
      refreshEach: false,
    },
  ];
  for (const [index, config] of configs.entries()) {
    const name = `bench_${Date.now()}_${index}`;
    await api("collections", { name, dtype: config.dtype });
    const docRuns = [],
      queryRuns = [];
    for (let repeat = 0; repeat < 3; repeat++) {
      const encoded = await embed(
        dataset.documents.map((d) => d.text),
        config,
      );
      const saved = await api(`collections/${name}/import`, {
        dtype: config.dtype,
        refreshEach: config.refreshEach,
        records: dataset.documents.map((d, i) => ({
          ...d,
          source: d.id,
          vector: encoded.vectors[i],
        })),
      });
      docRuns.push({
        loadMs: encoded.loadMs,
        embedMs: encoded.embedMs,
        backend: encoded.backend,
        fallback: encoded.fallback,
        ...saved,
      });
      for (const query of dataset.queries) {
        const start = performance.now(),
          q = await embed([query.text], config);
        const result = await api(`collections/${name}/search`, {
          dtype: config.dtype,
          text: query.text,
          vector: q.vectors[0],
          k: 3,
        });
        queryRuns.push({
          repeat,
          query: query.text,
          ids: result.hits.map((h) => h.id),
          queryEmbedMs: q.embedMs,
          searchMs: result.searchMs,
          endToEndMs: performance.now() - start,
          recall: recallAtK(
            result.hits.map((h) => h.id),
            query.relevant,
          ),
          ndcg: ndcgAtK(
            result.hits.map((h) => h.id),
            query.relevant,
          ),
        });
      }
    }
    report.runs.push({
      config,
      docRuns,
      queryRuns,
      summary: {
        backend: docRuns[0].backend,
        coldLoadMs: docRuns[0].loadMs,
        warmDocMs: median(docRuns.slice(1).map((r) => r.embedMs)),
        docsPerSecond:
          (dataset.documents.length /
            median(docRuns.slice(1).map((r) => r.embedMs))) *
          1000,
        writeMs: median(docRuns.map((r) => r.writeMs)),
        refreshMs: median(docRuns.map((r) => r.refreshMs)),
        searchMs: median(queryRuns.map((r) => r.searchMs)),
        queryEmbedMs: median(queryRuns.map((r) => r.queryEmbedMs)),
        endToEndMs: median(queryRuns.map((r) => r.endToEndMs)),
        recall: queryRuns.reduce((s, r) => s + r.recall, 0) / queryRuns.length,
        ndcg: queryRuns.reduce((s, r) => s + r.ndcg, 0) / queryRuns.length,
      },
    });
    lastReport = report;
    renderReport(report);
  }
  await list();
  $("status").textContent = "完整评测完成，可导出原始 JSON";
  // Accessible text also makes automation evidence inspectable without privileged browser state.
  $("report-json").textContent = JSON.stringify(report);
}
function renderReport(report) {
  $("report").replaceChildren();
  for (const r of report.runs) {
    const s = r.summary;
    $("report").append(
      node(
        "p",
        `${r.config.name} → ${s.backend} | ${s.docsPerSecond.toFixed(1)} docs/s | DB ${s.searchMs.toFixed(1)} ms | E2E ${s.endToEndMs.toFixed(1)} ms | Recall@3 ${s.recall.toFixed(3)} | nDCG@3 ${s.ndcg.toFixed(3)}`,
      ),
    );
  }
  const details = document.createElement("details");
  details.append(node("summary", "原始评测 JSON"));
  const pre = node("pre", JSON.stringify(report));
  pre.id = "report-json";
  details.append(pre);
  $("report").append(details);
}
$("benchmark").onclick = () => run(benchmark);
$("export").onclick = () => {
  if (!lastReport) {
    $("status").textContent = "请先运行评测";
    return;
  }
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(lastReport, null, 2)], {
      type: "application/json",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "stepfun-benchmark.json";
  a.click();
  URL.revokeObjectURL(url);
};
run(async () => {
  $("status").textContent = "连接本地 seekdb Server…请确保数据库已启动";
  active = localStorage.getItem("stepfun-active") || "";
  const all = await list(),
    c = all.find((c) => c.name === active);
  if (c) $("dtype").value = c.dtype;
  else active = "";
  $("status").textContent = active
    ? `已恢复知识库：${active}`
    : "准备就绪，请创建知识库";
});
