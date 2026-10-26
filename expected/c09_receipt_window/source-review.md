# C09 receipt-window 独立源码审查

本清单仅绑定本地冻结提交 `a31ac4bb9bbb7f7270e69d3848011eaeb986e981` 的候选。旧 C07 清单、候选与验收结论保持原样。

独立审查者复读冻结提交的 13 个变更文件并检查生命周期、同步回调、异常和普通接口隔离；明细见 `source-review.json`。本次修复隔离用户回调异常：Error 保持原对象；非 Error 和分类陷阱使用既有 CallbackFailure，不再进入 nativeError。旧 4edc8c7 候选、报告及 Lab 源清单已另存，不能用于修复后结论。主协调将本次冻结源码与旧清单逐项比较：原生清单只有测试 facade patch、baseline 和 PORTS 引用变化；Kotlin 清单只有测试 facade 生成器与 helper 合约引用变化。其他原生输入、KSP 输出、工具/头文件/固定上游及链接要求仍使用原精确身份，候选须逐项匹配。

主协调独立用 git apply 将测试 patch 应用到普通 Boundary 源码，核对结果哈希与 baseline，并更新三条原生测试路线的同一派生 facade 引用。Kotlin hook 属于 ArkTS facade，无 Kotlin 作者函数或 KSP 输出变化，因此不改旧 KSP 输出清单。实际候选若不匹配则拒绝，不能据其自身声明自动更新清单。

使用固定 `review_id="c09-receipt-window"` 入口；不接受候选指定清单或任意路径。此审查只证明有限源码及公开编译回执绑定，不是独立重建、目标执行、全部回归、全部平台或整包 C09 通过。普通和测试候选必须同 revision 配对，目标执行证据另行收集。
