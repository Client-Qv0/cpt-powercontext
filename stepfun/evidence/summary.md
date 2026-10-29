| 配置 | 实际后端 | 文档/秒 | 写入 ms | 刷新 ms | DB ms | 查询 E2E ms | Recall@3 | nDCG@3 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| FP32 / WASM / batch1 / refresh1 | WASM | 24.5 | 99.6 | 8045.8 | 3.0 | 28.0 | 1.000 | 1.000 |
| INT8 / WASM / batch1 / refresh1 | WASM | 37.7 | 119.7 | 7472.3 | 3.0 | 20.5 | 1.000 | 1.000 |
| INT8 / WASM / batch8 / refresh1 | WASM | 36.4 | 227.8 | 7472.2 | 3.1 | 22.9 | 1.000 | 1.000 |
| INT8 / WASM / batch8 / refreshBatch | WASM | 36.2 | 79.6 | 501.0 | 3.2 | 19.0 | 1.000 | 1.000 |
| INT8 / GPU优先 / batch8 / refreshBatch | WebGPU | 25.4 | 79.4 | 700.7 | 3.0 | 119.4 | 1.000 | 1.000 |
