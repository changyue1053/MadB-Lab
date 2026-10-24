# MadB 实施计划与阶段退出条件

交付独立 MadB 与 MadB-Lab，九组语言边界、十六条主线全部保留。阶段安排表示验收顺序；人员和设备未落实前不编造日历工期。当前实施与认证状态以[工作包目录](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/catalog/implementation-plan.json)为准。

## 计划的维护入口

目录维护 41 个工作包：30 个主线、11 个后续扩展。任务的责任、依赖、acceptance、文档及实际证据只在目录修改；[HTML 计划](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/visuals/implementation-progress.html)直接生成阅读视图。本文解释阶段和交付安排，避免维护第二份任务明细。

目录中的 `decision_gates` 对应 [ADR-0009](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/adr/0009-implementation-contracts-and-gates.md) 的 DEC-01 至 DEC-12，记录完成时点、规范、任务和验收。它们不是新增工作包，也不按“决策已写入”计工程完成度。

## Agent 开发的计划执行

全部工作包遵循[Agent 开发规范](../engineering/07-agent-development.md)。每次任务在现有任务、Issue 或 PR 中明确编号及子范围、相关设计依据、修改边界和验收方式，再实施、验证、交付；不另建任务协议或进度系统。

范围内实现由 Agent 自主推进；改变既定架构或契约先形成具体变更并按现有流程决策。文档、计划冲突只暂停受影响部分；已经明确授权的调整无需重复确认。子范围完成不提升整个工作包状态，未执行和缺证据不计通过。

C01 建立两工程的简短根 AGENTS.md、真实检查入口及合入约束，并复用一个实际小任务验证执行流程；各平台门禁随对应工作包补齐。这是协作基线的一部分，不新增工作包或全量测试前置。

## 阶段与依赖

| 阶段 | 主要工作 | 交付与退出条件 |
|---|---|---|
| S0 设计落地与探针 | 固化协议、工具链、目标和开源前提；建立双工程、扩展宿主契约和模板格式 | 首链六类资产的 S0 部分就绪，首链必需探针和 lock 可复现；其余探针有负责人和阻断点；扩展 schema、协商与框架探针通过，模板及 IDE 探针明确；不冻结全部语言 API |
| S1 最小完整链路 | Rust↔C、核心、CLI、候选包、Lab；独立扩展探针；rust-c-sdk 初始化 | Rust/C 两个直接方向、资源/回调/负例和独立候选消费通过；独立同步扩展通过；新工程可导入、构建、运行并随源码重建 |
| S2 Kotlin Swift Rust | UniFFI、Gobley、Kotlin/Native Swift；惯用 API；KMP/Rust 工程模板 | 四个对应主线配置通过；Android Studio/Xcode 工程及生命周期、IDE 重建通过 |
| S3 ArkTS 路线 | Kotlin、Rust、C、C++ 四个 ArkTS 配置；ArkTS 模板和鸿蒙组合配置 | 真实 SDK、env、线程、停止、页面和 HAP 通过；DevEco 导入运行、组合工具链兼容通过 |
| S4 其余原生路线 | Swift C/C++、Kotlin JVM/Native C/C++、Rust CXX 及对应消费模板 | 七个对应主线配置完成；工具链、对象、装载和适用 INIT 门禁通过 |
| S5 全产品发布 | 主线矩阵、推荐模板、文档旅程、性能、公开包与贡献流程 | 所有主线均有最低完整认证组合；所有必需问题闭环；推荐模板有 IDE 证据；候选原样发布 |
| S6 持续扩展 | NativeCoroutines、Swift export、ANI、FFM/JNA、Crubit、UniFFI ArkTS beta、KNOI、远程制品、专用 IDE 向导/深度插件 | 每项有独立范围、版本和测试；IDE 向导复用既有初始化用例 |

S2 与 S3 的核心路线在 S1 的协议稳定后可独立推进；I05 的多平台组合模板仍需 I04 的 Android/Apple 部分就绪。S4 的公共原生基础可提前开发，但退出条件不降低。UI 适配按对应平台阶段交付，不能仅以 CLI 跑通视为完成该平台。

工程初始化使用现有 `madb init`，不增加平行入口。原生 IDE 工程可用性属于 S1 至 S5 的主线要求，S6 仅增强向导和深度插件。


## C01 开工处理要求

C01 已获准启动；当前任务状态与实际负责人见工作包目录。下列事项纳入 C01 原有验收，不增加工作包、审批层或第二套进度。状态更新以真实证据为准。

| 事项 | 已采用的处理要求 | 完成时点 |
|---|---|---|
| 仓库和文档归属 | 工作区下 madb 与 madb_lab 分别建 Git 仓库；权威资料放入 madb/docs。原 docs 可保留单向兼容链接，不保留可独立修改的副本；Lab 使用固定来源和摘要的必要规范只读副本 | 首次提交前 |
| 检查可复现 | 提供固定 Python/Node、校验依赖锁与安装入口，独立检出和 CI 使用同一命令，不依赖本机临时目录；环境未安装完整时明确失败 | C01 首批交付 |
| 工具链锁 | 工具宿主采用已选 Rust 1.99.1 / Edition 2024，项目 rust-toolchain.toml 与 Cargo.lock 固定；只添加已使用的依赖，不升级用户全局默认工具链 | 首次构建前 |
| 身份与责任 | C01 负责人为已核对账号 changyue1053；落实 MadB、MadB-Lab 仓库及必要权限。自有 crate 初期 publish=false；未来渠道坐标取得前不声明已经占用 | C01 内 |
| Agent 与合入约束 | 两份简短根 AGENTS.md、实际检查入口、依赖负例及 CI 必需检查；用实际小任务验证失败不能放行。配置文件存在不等于远程约束生效 | C01 验收前 |
| 公开内容 | 落实既定 Apache-2.0 的 LICENSE、必要 NOTICE、第三方与历史资料权利清单；在核对完成前不公开未审核内容 | 首次公开代码前 |

C01 可先交付本地基线。若远程权限、命名空间或公开前核对仍未完成，保留明确未完成项，工作包不计验收通过。C01 不提前实现生成器、FFI 运行时、完整 IR 或语言便利 API；无实际实现的命令不能成功返回。首链格式和协议由 C02 完成，首链工具/目标及真实双向调用由 C03 完成。

## S0 的可执行交付

1. C01 按[工具骨架](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/architecture/02-modules-and-ports.md)与[Lab 骨架](../validation/02-lab-architecture.md)建立双工程、最小可编译 workspace、依赖检查，以及 Apache-2.0 设计默认所需的实际许可/通知、贡献、轻量 Agent 执行规范和 CI 合入基线；固定真实仓库/包命名空间与人员/设备责任。
2. C02 固定结构与语义权威、符号身份、精确选择器、默认展开、摘要和最小格式；项目/IR/锁/profile/案例/报告及首链 payload 有可执行正反样本。
3. C03 完成首链 P01/P02 的工具锁、两种布局及至少一个真实目标的双向调用；P03/P05 等尽早探针，只阻断受影响的后续配置。
4. E01–E03 通过扩展 schema、注册、握手、必需语义协商和框架探针；使用测试语言身份验证核心依赖不变。
5. I01 固定模板 schema、文件所有权、Wrapper 与原生 IDE 配方；L01 明确普通入口和机制责任，便利语法通过原型收敛。
6. 形成[首链六类资产](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/delivery/04-design-readiness-and-first-route.md)的 S0 部分：作者声明、ABI/生成预期、端口、profile/锁、消费者/独立预期及候选配方。首链集成必须满足 DEC-01 至 DEC-06 的设计与格式准入。

S0 包含真实原型和探针，不要求预先实现完整工具，也不等待所有语言的注解或属性封装器定名。高风险探针的证据与阻断范围由[风险登记](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/delivery/03-decisions-and-risks.md)维护。

## 工作线与交付责任

| 工作线 | 工作包 | 交付重点 |
|---|---|---|
| 核心与路线 | C01–C08 | 契约、CLI、首链、平台后端；DEC-01 至 DEC-10 的适用实现 |
| 验证与分发 | C09–C11 | S1 开始首链 Lab/候选，S5 收口矩阵与公开发布；DEC-10 至 DEC-12 |
| 扩展机制 | E01–E06 | S0 协议、S1 Dart Native→C 同步探针、S5 扩展作者交付 |
| 工程初始化 | I01–I06 | 模板与 Wrapper、IDE 日常增量、组合工程；沿用生成事务与输入追踪 |
| 语言体验 | L01–L07 | 普通 API、声明复用、按配置便利层、独立 DX 验证 |
| 后续扩展 | I07、L08、X01–X09 | IDE 向导、深度插桩及既定后端/服务扩展；独立版本与证据 |

C04 依赖 C01/C02/C03，C05 贯通 Rust/C。C06/C07 在首链稳定后可并行，C08 的原生基础可以提前验证。C09/C10 的 `start_phase=S1`、`phase=S5` 表示从首链提供能力，到全矩阵才完成整体验收；其依赖边是整体验收前置，C05 不等待 S5 收口。

E04 继续限定 Dart 同步子集。I05 组合模板需要 I04 的 Android/Apple 部分与 C07 的 ArkTS 部分，同时满足单一内核装配；路线分别通过不自动完成 I05。L03–L06 随对应平台交付普通入口及选用便利层，不能到 S5 才补生命周期。

S6 保留全部既定扩展：NativeCoroutines/SKIE、官方 Swift export、ANI、FFM/JNA、Crubit、新语言/目标、UniFFI ArkTS beta、KNOI、远程制品，以及 IDE 向导和深度插件。可以提前实验；对应 C11 依赖表示正式扩展验收前置，不表示禁止早期探针。

## 每项交付的完成标准

工作包提交问题/需求 ID、契约变化、具体输入输出、生成/手写分工、失败行为、适用案例、文档及兼容影响。后端交付包含 Reader/映射、生成接入、Toolchain、语言 API、Verifier 和独立消费，不能仅提交模板字符串。

- 准入决定已落实为格式、接口、任务图或明确的 profile 配方，并有正反例。
- 生成可再生、事务提交与输入追踪可靠；源码/产物/候选身份一致，手写文件保留。
- 适用的公开 API、资源/线程/取消、CRIT、INIT 与 DX 检查通过；未插桩 Release 独立验证。
- 报告绑定真实候选、工具、目标、Lab revision 和清理结果；缺环境、skip 或 unsupported 不代替必需项通过。
- 推荐模板可在原生 IDE 导入、构建、运行及修改后重建；承诺调试时另有断点证据。
- 发布候选包含依赖/许可/符号/来源，公共安装下载的是相同候选；生成模板和 runtime 的修复分别核对。

任务只有 `implemented + passed + 有效证据` 才计入验收。工作包数不是工时百分比；浏览器草稿、文档检查和图示不产生认证。预览可以交付明确子集；S5 完整版本需要每条主线的最低完整配置及全部适用必需项，变更承诺必须通过 ADR。

## 维护分工

架构负责人维护语义和 ADR；核心维护者负责规则、任务与事务；平台维护者负责 profile、上游配套和工具目标；验证维护者独立制定 oracle；发布维护者管理候选和公开渠道。具体 owner 与日期在目录落实，高风险原生/并发变更保留独立审查证据。

## 骨架建设与功能交付

C01 登记六个核心 crate 及实际启用的构建成员，建立代码检查和架构依赖负例；此时不以空目录或成功空实现宣称后端可用。C02/E01/E02 固定模型、格式、扩展清单和进程契约；C04 实现应用端口、组合根、任务执行与受控 host。C05 再贯通 Rust/C 适配器、公开候选和两个真实消费者，C09/C10 提供其 S1 所需验证与打包能力。

新增语言或便利层沿既定 sdk、adapter、helper 和模板边界接入，先检查是否复用已有实现。各工作包的具体依赖与验收仍只在实施目录维护；骨架落地不增加任务、完成率或认证。

## C03 交接与后续准入

[C03 记录](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c03-native-probes.md)按 P01/P02 保存实际结果，目录状态仍是唯一权威。首链的 C04/C05 不等待其他语言探针全部完成；P03/P05 由对应工作包尽早进入受控复现，模板修复先验证旧路径失败，再验证新路径。

C04 接收 C02 格式/契约和 C03 的真实锁/生成形状，完成宿主读取/执行端口、任务图、冻结输入、生成事务与缓存；C05 在这些端口上接入实际编译器来源 reader、语言生成器、完整资源协议和独立 Lab。C03 的 stateless 试验不能充当 C05 生命周期验收，也不代表 S0 其他必需工作已通过。

## C04 整包交付

C04 在六个历史子范围上完成整包编排。历史实现与当时的验证范围分别见[只读查询](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c04-readonly-queries.md)、[受控进程](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c04-process-execution.md)、[固定输入](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c04-frozen-inputs.md)、[单任务结果](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c04-task-results.md)、[静态 DAG](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c04-dag-execution.md)及[输入观察](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c04-input-observations.md)。这些历史记录不单独代表整包完成；当前验收见[整包记录](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c04-complete-package.md)，状态以任务目录为准。

| C04 验收 | 整包实现与证明 |
|---|---|
| 固定快照与模块隔离 | app 用例/端口、contracts 严格转换、host 受控 IO、CLI 组合根；真实依赖方向负例 |
| 只读查询与生成检查 | 显式 metadata 准备不要求已有 IR；`generate --check` 在自有临时目录复算，验证实际文件与身份，不修复有效输出 |
| 三层提交与固定消费 | Source/Build/Candidate、真实父批次证据、compile/link/run 完整构建、固定批次和祖先租约；新源码使旧 build/candidate current 失效 |
| 同域并发、取消与恢复 | owner 认领、短锁/CAS、输入最终复核、取消与索引替换线性化；真实多进程并发、迟到结果、重复提交、崩溃点和租约回收测试 |
| 完整输入与缓存 | 受限 freestanding Clang 真实依赖发现；工具/目标/宏/环境/传递头/缺失条件/搜索成员纳入身份；显式准备及后续绑定、命中复核和损坏隔离重建 |
| CLI 和独立消费 | 正式 generate/build/package、SIGINT/SIGTERM 取消、完整进程诊断；真实编译/链接/运行及独立候选消费者 |

完整门禁执行全部旧回归、新整包集成测试和文档/HTML 投影检查；远程 CI 绑定具体提交，不能从本地结果推导 Linux 通过。

C04 的缓存资格限于已有完整输入证明的原生配置；未知脚本与未支持参数保持不可缓存。进程终止恢复不代表断电或网络文件系统认证，保留目录不能冒充完整后代清理证明。

C05 接入实际编译器来源 reader、语言生成器、资源/线程/取消协议及独立 MadB-Lab 消费验收；复用 C04 端口，不以 fixture、候选生成或部分构建替代 SDK 认证。

## C05 首链实施范围与证据边界

首链通过 `scripts/install_native_tools.py` 安装锁定工具，由 `scripts/build_first_route.py` 串起真实声明读取、生成、构建与候选提交。实际适配器和独立 SDK 落点见[模块规范](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/architecture/02-modules-and-ports.md)；实现仅接收首链已知 roles 与编译器验证的声明，不推导任意 Rust/C 语义。工具端 `madb-native-finalize` 复用现有策略解析、来源与摘要规则，不成为公开 SDK 的运行依赖；只读查询继续不触发准备或生成。

交付三个独立候选：C→Rust 的未插桩 Release、单独 test-support profile，以及 Rust→C 的 C 库和公开 Rust 包装。C04 的静态 DAG 需要先显式 prepare 实际输出身份，再在冻结输入下重新编译、链接、运行并核对；准备结果和候选生成都不单独证明验收。默认生产入口要求干净检出；开发用 `--allow-dirty` 产物标为 provisional，不能用于正式 Lab 验收。

首链内部 adapter 配置由 read/lock 固定，profile 的 `backend_config` 保持 `null`；公开工具链记录去除宿主路径。Linux native observed profile 与 Apple 冻结工具链按各自真实目标取证，互不推导认证。独立 Lab 只接收公开候选，在无工具源码及开发缓存的新工程中运行两个直接消费者；整包完成仍要求目录中的全部 acceptance 和绑定最终候选的实际报告，此处不更新工作包状态。

## C05 整包验收

[C05 记录](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c05-rust-c-first-route.md)保存真实双向 SDK、三份公开候选、macOS Arm64/Linux x86_64 独立消费者与身份拒绝证据。五项 acceptance 已通过；MadB #11 与 MadB-Lab #2 的合入状态由 GitHub 记录。C09/C10 已开始 S1 首链部分，全部配置/渠道的整体验收仍缺证据，不能据此标为完成。下一核心工作包按目录进入 C06；不在 C05 中扩展其他语言。
