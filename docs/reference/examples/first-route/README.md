# 首链 ABI v1 的可执行设计

本目录是 C02 的审查基线：固定两条直接路径需要的声明、状态值、缓冲、句柄和停止协议。`expected.h`、`expected.rs` 都是手写的**预期形状**，不冒充 cbindgen/bindgen 输出。`consumer.c` 只做签名与布局编译检查；C03 固定上游工具和两个目标的真实生成形状，C05 交付实现及独立消费者。当前没有可安装或运行的 SDK。

## 资产与责任

| 资产 | 作用 | 后续验证 |
|---|---|---|
| [C 声明](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/examples/first-route/expected.h) | Rust 提供方的预期导出面及独立 C 提供方入口 | C03 cbindgen 对照；C05 实际符号、链接及 C 消费 |
| [Rust 声明](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/examples/first-route/expected.rs) | `repr(C)`、数值状态和 `unsafe extern "C"` 导入形状 | C03 bindgen 对照；C05 独立 Rust 消费 C |
| [C 消费片段](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/examples/first-route/consumer.c) | 字段偏移、宽度、状态常量及函数签名 | 本机编译；不等于运行或双目标探针通过 |
| [格式与语义样本](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/tests/fixtures/contracts/README.md) | 五个端口的独立样本、领域身份、策略来源与反例 | C02 跨实现检查；C04 端口执行、C05 真实读取器 |

C ABI 是“状态返回 + 输出参数”；IR 的 `result: engine/u64/unit` 表示逻辑结果。C05 降低到 `MadbStatus` 与 `out_*`，失败状态不混入逻辑返回类型。格式样本覆盖五个基本接口；本目录还固定观察接口与 Rust 独立消费 C 的入口。观察接口的真实读取与有效策略由 C03/C05 补齐，不据此声称样本已覆盖所有回调运行路径。

## 数值、缓冲和错误

状态权威为 `expected.h`：0 成功，1 InvalidArgument，2 InvalidHandle，3 Closing，4 Closed，5 Busy，6 Timeout，7 WouldDeadlock，8 InternalFailure，9 ResourceExhausted，10 DomainError，11 Unsupported。状态载体固定 `int32_t`，不把 C enum 的实现宽度暴露为 ABI。

- 输入是只读字节缓冲，长度单位为 byte，最大 65536；`data == NULL` 仅允许长度为 0。非零长度要求指向调用期间有效的可读内存；无法验证任意地址是否有效。
- checksum 是所有字节按无符号整数求和；空缓冲结果为 0。该上限下不会溢出 `uint64_t`。超过上限或长度无法转换为目标 `size_t`，返回 InvalidArgument。
- 所有 `out_*` 都要求非空、有效、对齐且互不重叠。进入操作时先将每个**有效**输出位置清零，再做句柄/业务校验。任意非法裸指针属于调用者违约，不能保证返回错误代替未定义行为。
- `MadbError { domain: uint32_t, code: int32_t }` 没有堆内存。成功和生命周期失败时两项为 0；仅 DomainError 携带非零稳定 domain 与领域 code。不能让异常或 panic 穿越 C ABI；可捕获失败映射 InternalFailure，abort 配置不承诺返回。
- 句柄是所属 SDK 实例的登记令牌，0 无效，单调分配、不复用，耗尽返回 ResourceExhausted。包装另记来源实例；令牌不是全局指针或安全认证凭证。

## 关闭、观察及 context

`request_close` 原子关闭新操作准入，非阻塞，重复请求返回同一次关闭的结果。`await_closed(timeout_ms)` 成功必须意味着该句柄负责的工作、消费者回调和资源清理已完成；0 表示只检查状态，尚未完成返回 Timeout。超时不强制释放，不恢复为 Open。未请求关闭时返回 Busy。

`release_handle` 只在 Closed 后移除登记；Open/Closing 返回 Busy；移除后包括重复 release 在内均为 InvalidHandle。普通业务调用在有效 Closing/Closed 登记上分别返回 Closing/Closed。`request_close/await_closed/release_handle` 接受 engine 或 subscription；checksum/observe 必须是 engine，类型不符返回 InvalidHandle。

观察的最低协议为：

- 注册可在返回前同步调用一次；后续回调在该订阅的串行源端执行序列上调用，允许回调内非阻塞请求关闭。不得持有登记表锁调用用户代码。
- callback 非空，context 可为空；context 不转移，调用者从注册开始保活到停止排水完成。注册失败在返回前排水、输出 subscription=0，此后不得再访问 context。
- 同步首回调尚未取得返回的 subscription，可使用已持有的 engine 请求关闭；若此时关闭 engine，注册返回 Closing，完成失败回滚和排水后输出 subscription=0。
- 成功返回 subscription 只表示已注册。重复值可交付，sequence 在该订阅内递增；本版本无消费者队列和历史回放，不承诺丢失事件恢复。回调必须有界返回，不得同步等待自己的退出。
- subscription 的 `request_close` 停止接纳新回调；已获取的回调许可可完成，`await_closed` 等待排水。回调内对本订阅或等待该回调的 engine 调用 `await_closed` 返回 WouldDeadlock。
- engine 关闭也关闭其订阅并排水；成功后 context 可清理。subscription 的登记令牌仍由其调用者 release，避免引擎替消费者消费令牌；源端 owner 负责保持所需记录直到排水完成。

上述是待 C05 验证的协议，不是 C02 的并发正确性证据。首链要求的错句柄、重复关闭、关闭超时、迟到回调、注册失败和同步反调见 [CRIT-03/08/11](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/validation/08-critical-scenarios.md)。

## 来源诊断与拒绝基线

以 `tests/fixtures/contracts/contract-ir.json` 的 checksum 为例：reader 标记源位置 `native/fixture.rs:20:1`，项目策略独立保留配置位置。将该调用改为 async 而沿用 call-frame 借用，纯规则产生 `SEM008`，subject 为完整公开 ID，location 指向声明；两个相同显式 ownership 也产生 `POL004`，保留两个来源位置。测试从结构样本构造反例，断言诊断代码及位置，不从失败实现反推预期。

缺释放器、错 release 签名、未知强制语义、缺 C record 布局、来源为 heuristic 都在生成前阻断。schema 正例只能证明可解码；冻结输入、策略来源、类型能力、真实字节摘要和执行证据分别检查。

本目录不包含 ABI 兼容承诺；第一份对外版本前仍须完成 C03/C05 并审查实际生成差异。改变本设计要同步声明、样本、测试与对应决定，不只修改一个语言的镜像。

## C03 生成验证补充

[真实探针](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/tests/integration/c03/README.md)已将本目录的完整 ABI 声明经 cbindgen/bindgen 生成并在两个 Apple 目标编译；运行部分使用独立 stateless provider，未实现这里的 engine 生命周期。

`expected.h` 的状态码改用普通整数宏：锁定版本 bindgen 未导出 `INT32_C(...)` 表达式，且普通非负宏默认映射为 u32，因此参数固定 `--default-macro-constant-type signed`。全部 12 个状态码继续被编译断言为原 i32 数值；没有改变 ABI、状态机或错误语义。不能把消费者强制转型当成生成正确。

## C05 bootstrap 与公开候选约定

固定入口为 `int32_t madb_fixture_bootstrap(uint32_t requested_version, uint8_t *out_identity, uint64_t capacity)`；独立 C 提供方使用相同签名的 `madb_c_fixture_bootstrap`。版本 1 要求非空且有效的 64 字节输出区、capacity 精确为 64。有效输出先清零；错误指针/容量返回 InvalidArgument，再检查版本，未知版本返回 Unsupported。成功写入 32 字节 interface 摘要和 32 字节 profile 摘要，均按摘要十六进制解码的原始顺序，无分配、无业务调用。任意无效内存地址仍属调用者违约。

interface 摘要来自实际公开 ABI 与 `madb.first-route/1` 语义版本；profile 摘要使用既有投影。它们不是 candidate_digest 或业务 ContractIR 摘要的别名。生成的公开包装与库使用同一预期值；消费者先验证候选文件，再执行 bootstrap，分别报告 ArtifactMismatch、AbiMismatch 或 ProfileMismatch。缺 bootstrap、错目标在链接/装载阶段拒绝，不能试调未知业务签名。

每个候选携带入清单的 `identity.json`：`{schema:"madb.native-identity/1", bootstrap_version:1, interface_digest:"sha256:…", profile_digest:"sha256:…"}`，以及 `provenance.json`：`{schema:"madb.native-provenance/1", producer_revision:"<40hex>", input_digest:"sha256:…", tool_digest:"sha256:…"}`。后者记录真实源集合身份与 producer 可执行文件摘要，不授予认证资格。

候选根分别为 `c-to-rust`、`rust-to-c` 和单独的 `c-to-rust-test`。每根包含自己的 candidate.json、profile/lock、证据、许可和文件清单。C 消费 Rust 使用 include/madb_rust.h 与 lib/libmadb_engine；Rust 消费 C 使用 include/madb_c.h、lib/libmadb_c.a 及 rust/madb-c-client 公开包。生成 raw.rs 和 identity.rs 随包交付，消费方无需安装 bindgen。

观察 v1 的公开初始状态为 sequence=1/state=0；当前没有领域事件生产器、消费者队列、计时器或回放。test-support 的 source emit 驱动同一生产租约机制，屏障设在操作准入后与源取得 callback/context 后。默认 Release 不导出测试入口；测试候选分别提供资源/许可/回调计数和受控故障。异步停止排水要求保持不变，不能把“无消费者队列”解释为回调可提前释放。

C05 开发期候选可以显式使用 `--allow-dirty`，此时 `provenance.json` 的可选 `provisional: true` 必须传播到 Lab 报告；正式验收拒绝该候选。默认构建要求生产仓库干净，`producer_revision` 绑定实际提交；`input_digest` 仍绑定本次源字节，不能用 revision 或 provisional 替代。
