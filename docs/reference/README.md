# 固定规范引用

来源：[MadB C06 固定提交](https://github.com/changyue1053/MadB/tree/0daf56372c721059be5cc49f80857dd79941cf9d/docs)。REVISION 固定来源，SHA256SUMS 校验七份导出规范的实际字节；导出文档之间保留相对链接，未附带文件的相对链接展开到同一固定提交。除链接目标转换外，规范正文来自该提交的原始文件。

这些文件是独立 Lab 的只读规范快照，不是第二套可修改规范或任务进度。共同规范和当前状态仍在 MadB 维护；更新时重新导出固定提交并审查差异，不能修改快照来迁就测试。

快照包含共同工程规范、Lab 架构、实施计划，以及 [C05 首链指南](examples/first-route/README.md)和 [C06 四路线指南](examples/managed-routes/README.md)。C05 与 C06 消费者只接收公开候选，运行时不检出或导入 MadB 源码。构建工作流另起 producer job，固定来源提交生成候选，再由隔离 consumer job 验证。

当前 C06 范围为 macOS Arm64 Release 上的 Kotlin/JVM → Rust、Kotlin/Native → Rust、Swift → Rust、Swift → Kotlin/Native；不外推 Android、iOS、其他平台或 KMP-NativeCoroutines 扩展。更新此快照及通过 Lab 仓库检查不表示 C06 正式验收通过；仍需固定双方提交与完整四路线候选的全部必需验证。
