# C05 消费与失败场景

运行入口：`python3 scripts/verify_first_route.py --candidates <完整候选根> --output <报告目录>`。参数缺失不会降级为基线通过。

| 独立程序 | 实际场景 |
|---|---|
| C → Rust Release | data、lifecycle、observe、bootstrap |
| C → Rust 测试候选 | operation-close（CRIT-08）、source-lease（CRIT-03）、registration-failure、panic、diagnostics、token-exhaustion、capacity |
| Rust → C Release | data、bootstrap；另链接两份 Lab 自有错库检查 AbiMismatch/ProfileMismatch（CRIT-12） |
| 安装 harness | 实际候选副本被修改后，在执行前准确 ArtifactMismatch；路径、符号链接、额外/缺失文件和错误摘要另有正反例 |

两条直接方向分别编译和运行，消费期间只有 Lab 与已安装候选。错误库仅写入隔离副本，原候选运行后再次校验。C05 当前无消费者任务队列；CRIT-11 的容量、重入与停止在本配置上验证，不声称运行了其他语言环境退出或事件队列场景。

报告中的 `passed` 必须来自真实退出、完成记录和独立断言。崩溃、无输出、watchdog、缺工具均不算预期负例。源代码/格式测试也不能替代实际候选的编译、链接和运行证据。
