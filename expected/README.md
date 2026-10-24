# C05 的独立预期

来源是公开 ABI 和生命周期契约；实现检查从 Lab 手写数据与后条件出发，不调用 MadB 规则引擎取得期待值。

- checksum：`[] → 0`，`[0,1,127,128,255] → 511`，65536 个 255 → 16711680。空指针仅与零长度配对；65537 字节在读取前拒绝。
- 生命周期：Open 时等待/释放 Busy；在途工作持有许可时关闭后新操作 Closing、等待 Timeout、释放 Busy；排水后 Closed；移除登记后 InvalidHandle；令牌不复用。
- context：源已持有租约时保持有效；await_closed 成功后才允许清理；最终资源创建/释放守恒，callback 开始/结束相等。
- 注册：同步首回调 sequence=1/state=0；回调内关闭非阻塞，等待自身返回 WouldDeadlock；失败注册输出 0 并排水，不交付隐藏 token。
- 原生测试：诊断故障不改变业务状态；panic 映射 InternalFailure，所有有效输出清零。64 个订阅占槽，关闭未 release 仍占槽；控制路径在满容量下可完成。最后可用 token=UINT64_MAX，其后 ResourceExhausted。
- 制品：完整性失败在执行业务前 ArtifactMismatch；不匹配实际 C 库必须由安全包装返回 AbiMismatch/ProfileMismatch，错库业务函数以 abort 证明未被调用。

`cases/` 的模板引用手写消费者并固定来源摘要。执行时只补实际 selector 得到实例与 case_digest；输入或预期变化会改变证据身份。
