# Knowledge Lab · 技术说明

**模型与量化。** 使用公开开源 [Xenova/all-MiniLM-L6-v2](https://huggingface.co/Xenova/all-MiniLM-L6-v2)，固定 revision `751bff37182d3f1213fa05d7196b954e230abad9`（原始 sentence-transformers 模型，Apache-2.0）。采用发布者导出的动态 INT8 ONNX `model_quantized.onnx`，包含 DynamicQuantizeLinear / MatMulInteger；对照为同 revision 的 FP32 `model.onnx`。`npm run models` 下载两者并校验固定 SHA-256。实测 ONNX 为 90,387,606 / 22,972,370 bytes；同口径计入相同配置及分词文件后为 **91,100,408 / 23,685,172 bytes，压缩比 3.846×**。文件明细见 `data/model-manifest.json`。

**端侧与数据。** Transformers.js **4.3.2** 在浏览器 Worker 推理；显式 `device: webgpu` 优先，adapter 不存在或初始化失败自动使用 `device: wasm`，界面显示后端与原因；强制 WASM 开关可复测 CPU 路径。文档、查询均本地计算，mean pooling + L2 normalization、384 维；复用模型、默认 batch 8。模型、ONNX Runtime 的 factory/WASM 均可本地加载，无云端推理 API。seekdb-js `seekdb@1.4.0` 保存 ID、原文、向量与来源；HNSW cosine + beng 全文索引，`hybridSearch` 在数据库完成两路召回和 RRF。每次导入 upsert 后一次刷新；按库串行保护可见性，目录表绑定模型版本/精度，SHA-256 分块 ID 保证重复导入幂等，切库后清空旧结果。

**实测条件。** 2026-10-29，Windows 11 / Chrome 156，i7-14650HX（24 线程）、32 GB RAM；seekdb Server `5.7.25-OceanBase seekdb-v1.4.0.0` 位于本机 WSL，2 CPU、2 GiB 数据库内存配置。相同 12 篇英文文档、6 条人工标注查询，K=3；每种配置重复 3 次，原始数据见 `evidence/benchmark.json`。所有配置的 **Recall@3 与 nDCG@3 均为 1.000，量化质量变化为 0**。

| 配置 | 文档/秒¹ | 写入 ms | 刷新 ms | DB ms | 查询 E2E ms |
|---|---:|---:|---:|---:|---:|
| FP32 / WASM / batch1 / 逐条刷新 | 24.5 | 99.6 | 8045.8 | 3.0 | 28.0 |
| INT8 / WASM / batch1 / 逐条刷新 | 37.7 | 119.7 | 7472.3 | 3.0 | 20.5 |
| INT8 / WASM / batch8 / 逐条刷新 | 36.4 | 227.8 | 7472.2 | 3.1 | 22.9 |
| INT8 / WASM / batch8 / 批次刷新 | 36.2 | 79.6 | 501.0 | 3.2 | 19.0 |
| INT8 / WebGPU / batch8 / 批次刷新 | 25.4 | 79.4 | 700.7 | 3.0 | 119.4 |

¹吞吐按后两轮文档推理中位数计算，其余为全部相应样本中位数。首次模型加载/初始化 FP32-WASM 1315.3 ms、INT8-WASM 207.8 ms、INT8-WebGPU 847.0 ms；模型来自本地静态文件，浏览器可能命中缓存，**不是公网冷下载指标**。首次文档推理、后续加载、查询向量化和每次查询耗时均保留在原始 JSON。E2E 含查询向量化、HTTP 与数据库处理，到结果可渲染为止。

**结论与验证。** 同后端/批大小比较，INT8 吞吐约为 FP32 的 1.54×；单独改变刷新策略，刷新中位耗时减少约 93.3%。当前短文本小样本中 batch 8 未提高推理吞吐，WebGPU 也慢于 WASM，因此不宣称这两项加速。WebGPU 与强制 WASM 核心流程均实际运行；真实 Server 集成测试验证新增可检索、幂等、隔离、重新连接和精度校验。样本有限，不能外推到大语料。复现入口及 Docker 配置见 `README.md`。
