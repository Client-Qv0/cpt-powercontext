# 提交验证记录

- `benchmark.json`：最终应用在 Chrome 156 / Windows 上点击「运行完整评测」生成的全部原始记录，Transformers.js 4.3.2。5 种配置、每种 3 次导入、每条查询 3 次，未删除最慢值。固定输入与相关性标注在 `../data/evaluation.json`。
- `summary.md`：由 `node scripts/summarize.mjs` 从原始记录计算出的汇总表。
- `model-files.json`：实际下载文件的字节数、SHA-256 和同口径压缩比，与模型固定清单一致。
- `unit-tests.log`、`database-tests.log`、`dependency-audit.log`、`build.log`：行为测试、真实 seekdb Server 集成测试、依赖审计和生产构建输出。
- `webgpu-incremental.png`：12 篇示例语料之后追加第 13 篇文档，索引刷新成功后检索，新增文档排名第一，页面显示 WebGPU。
- `wasm-incremental.png`：同一知识库与查询，强制 WASM 下新增文档排名第一。
- `isolation.png`：切换到空知识库，同一查询返回 0 条。

本地数据库为 WSL 内真实 seekdb 1.4.0 Server，测试网关使用端口 5187、数据库端口 12884、独立数据库 `stepfun_lab_20261029`。默认交付配置使用 5173 / 2881 和 `test`，算法与 API 路径相同。测试仅在本次新建的数据库中写入，不依赖其他项目的预计算向量。Server 集成测试另建临时数据库并在结束后清理，覆盖增量、刷新、幂等、库隔离、客户端重连与模型精度拒绝。

WebGPU 与强制 WASM 均实际执行了本地 embedding 和数据库检索。未修改系统 GPU 开关来制造无 GPU 环境；自动降级由 adapter 检查及初始化异常分支实现，强制开关验证 WASM 核心流程。当前机器没有 Docker，镜像配置未执行，真实 Server 路径已验证。嵌入式原生引擎在当前环境遇到加载/进程退出问题，因此交付使用本地 Server。

模型已从本地 HTTP 静态目录提供；首次加载数据不代表公网模型下载。小规模语料中全部质量指标为 1.000，仅说明此固定评测集的观测结果。
