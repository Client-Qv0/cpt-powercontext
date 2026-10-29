import { readFile } from "node:fs/promises";
const report = JSON.parse(
  await readFile(process.argv[2] || "evidence/benchmark.json", "utf8"),
);
console.log(
  "| 配置 | 实际后端 | 文档/秒 | 写入 ms | 刷新 ms | DB ms | 查询 E2E ms | Recall@3 | nDCG@3 |",
);
console.log("|---|---|---:|---:|---:|---:|---:|---:|---:|");
for (const run of report.runs) {
  const s = run.summary;
  console.log(
    `| ${run.config.name} | ${s.backend} | ${s.docsPerSecond.toFixed(1)} | ${s.writeMs.toFixed(1)} | ${s.refreshMs.toFixed(1)} | ${s.searchMs.toFixed(1)} | ${s.endToEndMs.toFixed(1)} | ${s.recall.toFixed(3)} | ${s.ndcg.toFixed(3)} |`,
  );
}
