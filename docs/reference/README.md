# 固定规范引用

来源：[MadB C05 固定提交](https://github.com/changyue1053/MadB/tree/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs)。REVISION 固定来源，SHA256SUMS 校验六份导出规范的实际字节；未附带文档的链接展开到同一固定提交。

这些文件是独立 Lab 的只读规范快照，不是第二套可修改规范或任务进度。共同规范和当前状态仍在 MadB 维护；更新时重新导出固定提交并审查差异，不能修改快照来迁就测试。

C05 消费者只接收公开候选，运行时不检出或导入 MadB 源码。构建工作流另起 producer job，固定本提交生成候选，再由隔离 consumer job 验证。
