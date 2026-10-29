# 代码修改前后测试结果

- 生成时间：2026-10-29T08:06:30+08:00
- 验证脚本：`scripts/verify_change.py`
- 代码版本：`3d3c4e73f7f164aee69b2ad42758013a933dcb2a`

| 阶段 | 退出码 | passed | failed | errors | 期望 | 结果 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| before.target | 1 | 0 | 8 | 0 | exit=1 且存在真实断言失败 | PASS |
| before.regression | 0 | 23 | 0 | 0 | exit=0 | PASS |
| after.target | 0 | 8 | 0 | 0 | exit=0 | PASS |
| after.regression | 0 | 23 | 0 | 0 | exit=0 | PASS |
| after.full | 0 | 32 | 0 | 0 | exit=0 | PASS |

日志位置：`evidence/test-logs/`（每条日志头部记录命令、工作目录、退出码与代码版本）。

基线快照：`F:\OceanBase\powercontext\cpt-powercontext\minimax\evidence\baseline\sample_project.zip`
