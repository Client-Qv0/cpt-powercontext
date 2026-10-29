# Knowledge Lab：浏览器端向量化与 seekdb 混合检索

本目录为「端侧 AI 推理性能优化与 seekdb 混合检索」题目提交。基于 `2026-competition-ecosystem`，全部新增项目资产位于 `stepfun/`。

## 启动

需要 Node.js 22+、npm、Docker / Docker Desktop 和 Chrome / Edge 最新版。应用采用本地 seekdb Server；浏览器可在 Windows、Linux、macOS 上使用。首次安装需要网络下载 npm 依赖、模型和 seekdb 镜像；之后模型可从本地静态目录加载，无需模型 API key。

```sh
cd stepfun
npm ci
npm run models
npm run db:up
npm run db:ready
npm run dev
```

打开 `http://localhost:5173`。`compose.yaml` 固定官方 seekdb 1.4.0 镜像及摘要，仅映射本机端口，使用 Docker 命名卷持久化。数据库至少需要 2 GiB 内存和约 6 GiB 磁盘空间，首次初始化需等待 `db:ready` 成功。`docker compose stop` 暂停数据库，`docker compose start` 恢复；保留卷即可保留知识库。

生产构建：`npm run build && npm start`。模型文件会随 `public/models` 复制进 `dist`，必须先完成 `npm run models`。`npm test` 运行行为测试；`npm run test:db` 创建独立临时数据库，运行真实 seekdb 集成测试后清理该测试库。

如已有本地 seekdb Server，可通过环境变量配置 `SEEKDB_HOST`（默认 127.0.0.1）、`SEEKDB_PORT`（默认 2881）、`SEEKDB_USER`（默认 root）、`SEEKDB_PASSWORD`、`SEEKDB_DATABASE`（默认 test，需预先存在）。数据库须支持 `DBMS_HYBRID_SEARCH.SEARCH` 及 `CALL dbms_index_manager.refresh()`，建议 seekdb 1.3+。网关仅绑定本机 `127.0.0.1`，端口用 `PORT` 修改。

本次实测使用本机 WSL 的 seekdb 1.4.0 Server，Node 网关运行于 Windows。Docker 启动配置按[官方镜像说明](https://github.com/oceanbase/docker-images/tree/main/seekdb)提供，当前设备未安装 Docker，因此未实际执行 compose。提交的默认与验收路径均使用 Server 模式。

## 演示流程

1. 输入小写知识库名称，例如 `my_notes`，选 INT8，点击「创建 / 打开知识库」。
2. 选择多个 `.txt` / `.md`，或粘贴文本。点击「本地向量化并导入」；也可点击「导入示例语料」。
3. 等待状态显示「已就绪」。向量和原文已写入 seekdb，索引刷新已完成。
4. 输入问题并点击「检索」。界面展示 seekdb 排序后的原文、来源和分阶段计时。
5. 再导入新文档验证增量检索；重复导入同样内容不会重复增加分块。切换知识库后结果立即清空，后续请求使用所选知识库。
6. 勾选「强制 WASM」验证 CPU 路径；取消勾选时优先初始化 WebGPU，adapter 或模型初始化失败自动降级并显示原因。

模型为英文 `all-MiniLM-L6-v2`，内置可复现实验使用英文；中文文本可导入，但此模型不承诺中文检索质量。长文按 600 字符、80 字符重叠切块，模型最多处理 256 tokens，极端长 token 文本会被截断。单文件最多 1 MiB，每次导入最多 256 块。

## 实验复现

点击「运行完整评测」。程序真实调用同一浏览器 Worker 和相同 API 路径，自动建立隔离的 `bench_*` 知识库，按固定顺序测试：

- FP32 / WASM / batch 1 / 每条刷新。
- INT8 / WASM / batch 1 / 每条刷新：与上一行比较量化。
- INT8 / WASM / batch 8 / 每条刷新：只改变 batch。
- INT8 / WASM / batch 8 / 批次刷新：只改变刷新策略。
- INT8 / WebGPU 优先 / batch 8 / 批次刷新：只改变推理后端。

固定 `data/evaluation.json` 中 12 篇文档、6 条人工标注查询。每种配置运行 3 次文档导入和每条查询；保留所有原始值，计算中位数及 Recall@3、二元相关性 nDCG@3。首次加载（下载+初始化）、后续加载、向量化、写入、刷新、查询向量化、DB 检索和端到端耗时分开记录。端到端从查询提交前到 JSON 结果可用于渲染，不含浏览器下一帧绘制。首轮文档推理与后两轮分开保存；吞吐用后两轮中位数。模型下载可由浏览器缓存或本地静态文件命中，报告必须保留实际缓存条件。

「导出原始 JSON」保存本轮结果。`evidence/` 保存提交时实际执行的数据及说明，不应用此小规模样本推断生产规模性能。评测库为真实持久化数据，不会自动清除；重复运行会增加独立评测集合。

## 实现与数据结构

`src/embedding.worker.js` 在用户浏览器执行 Transformers.js 推理。文档与查询都使用 mean pooling、L2 normalization、384 维；Worker 串行处理，批大小默认 8，复用已加载模型，型号/精度/后端变化才释放并重建。服务端不安装 embedding provider，不接受 `queryTexts` 自动向量化。

`server/store.mjs` 使用官方 **seekdb-js 的 npm 包 `seekdb`**。知识库集合包含 SDK 定义的 ID、document、embedding、metadata，向量索引 cosine HNSW，document 上为 `beng` 全文索引。`stepfun_catalog` 表持久化知识库名称、精度和完整模型签名，重启后也校验，禁止把 FP32 查询送入 INT8 库。文档元数据含 source 和 dtype，ID 为来源+分块序号+内容的 SHA-256。

写入使用 `collection.upsert({ embeddings, documents, metadatas, ids })`，一次导入后调用 `refresh_index()`；只有刷新成功才报告完成。每个知识库的写入/刷新/查询按队列串行，保证正在导入时不会读取半个批次。数据库异常会返回错误，不会伪装为导入成功；失败的幂等批次可以重试。

混合检索仅调用 `collection.hybridSearch`，输入浏览器生成的 `queryEmbeddings` 与全文 `$contains`，`rank: { rrf: {} }`。候选产生和融合排序均由 seekdb 的 `DBMS_HYBRID_SEARCH` 完成，前端只展示返回顺序。语义模式调用 `collection.query`，不使用本地向量扫描或其他存储数据库。

模型来源与文件校验、体积统计及实测摘要见 [TECHNICAL.md](TECHNICAL.md)。所有依赖由 `package-lock.json` 锁定。`.npmrc` 禁用可选 embedding peer 的自动解析，以避开该上游包的 `workspace:*` 发布声明；不影响 seekdb 存储能力。
