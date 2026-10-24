# MadB-Lab

MadB 的独立公开候选消费与解决方案工程。仓库检查、实际 SDK 消费和工作包验收分别记录；任务状态以 MadB 的权威 catalog 为准。

使用 Python 3.14.4，在仓库根运行仓库与 harness 检查：

```sh
python3 scripts/check.py
```

此命令只使用 Python 标准库，检查固定规范、仓库隔离和 harness 的准确失败行为，不声称运行过 SDK。

## C05 公开候选消费

先取得固定 MadB revision 按公开 `scripts/build_first_route.py` 产生的完整候选目录。Lab 不导入 MadB 私有 crate，也不在消费时重生成绑定。候选根必须包含 `c-to-rust`、`rust-to-c` 和单独的 `c-to-rust-test`；每项有 `candidate.json`、`identity.json`、`provenance.json`、公开声明/包装、实际库及完整字节摘要。

在匹配候选目标的 macOS Arm64 或 Linux x86_64 环境，安装 Rust 1.99.1 和 Clang 后运行：

```sh
python3 scripts/check.py --first-route \
  --candidates /absolute/path/to/candidates \
  --output /absolute/path/to/reports
```

缺候选、编译器、错误目标或超时均失败。C 使用真实生成头及 Rust 动态库；Rust 使用候选公开 `madb-c-client` 包及 C 静态库。两个独立程序在新临时工程、空 HOME/CARGO_HOME/target 中编译运行，Cargo 离线解析，不安装 MadB CLI。生成器只在独立 producer 中使用。

正式验收要求 Lab 工作区干净，报告 revision 与实际 HEAD 相同。开发中可直接调用 `scripts/verify_first_route.py` 并增加 `--allow-dirty`；结果会标记 `provisional` 并附实际源码摘要，不能登记为固定提交的正式验收。

每次先核对完整候选文件及 bootstrap 的接口/profile 身份，再运行业务。Release 验证数据、状态/关闭、同步回调与重入；测试候选另以原生 barrier 验证在途关闭、源端 context 租约、注册回滚、panic、诊断故障、容量和令牌耗尽。独立预期见 [expected](expected/README.md)，实际测试映射见 [场景说明](scenarios/distribution/README.md)。回调不能替代 Rust→C 直接方向；未插桩 Release 不能被测试候选替代。

报告使用公开 `madb.report/1`，保留固定候选/输入/工具/profile/Lab/case 身份、命令、结果、资源后条件和清理。普通 `reports/`、下载和设备输出不提交。watchdog 杀进程仅表示错误，不算 SDK 成功取消。

## CI 与规范

原有 `MadB-Lab C01 baseline` 检查保留。C05 工作流的 producer 固定公开 MadB commit，交付候选 artifact；新的 consumer job 只检出 Lab 并下载候选，不共享生产源码与缓存。Linux 的真实结果只适用于 Linux profile，不能证明 Apple 目标；macOS Arm64 使用对应冻结工具链另行实跑。

[Agent 入口](AGENTS.md)、[贡献方法](CONTRIBUTING.md)、[只读规范快照](docs/reference/README.md)与 [LICENSE](LICENSE)、[第三方范围](THIRD_PARTY.md)适用。规范快照按已评审的 MadB 提交统一更新，不在 Lab 单独改写。
