# MadB Lab 独立验证工程

MadB-Lab 是解决方案目录与黑盒验收工程。它从版本化工具包、运行时及生成的 SDK 出发，验证一个没有开发者本机环境的使用者能够完成相同操作。

C01 使用独立 madb_lab Git 根建立可运行的仓库检查。首期不伪造候选包、tool.lock 或 FFI 测试通过；这些内容由 C02/C05/C09 按实际格式和候选补齐。必要的共同规范以固定工具仓库提交和摘要附带只读引用资料，当前任务状态仍以工具仓库 catalog 为准，不在 Lab 维护第二份计划。

## 验证工程的目标目录

本节是 MadB-Lab 目录的唯一维护入口；工具源码目录见[MadB 工程骨架](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/architecture/02-modules-and-ports.md)。以下为实施目标，按场景与目标逐步建立，不表示所有消费者已经实现。

<!-- madb-lab-tree:start -->
```text
MadB-Lab/
├── README.md
├── AGENTS.md                         # 独立验证规范和检查入口；C01 落地
├── .python-version                 # 首期仓库检查使用 Python 标准库
├── scripts/check.py                  # 独立仓库检查入口
├── tool.lock                         # 固定工具、候选、后端和目标身份
├── cases/
│   ├── types/                        # 类型、空值、数值与快照
│   ├── errors/                       # 业务失败、取消与边界错误
│   ├── ownership/                    # 借用、转移、关闭与最终释放
│   ├── async/                        # 完成、取消、观察与结果交接
│   ├── threading/                    # 执行器、重入、排水与环境退出
│   ├── ui/                           # 页面、输入与状态同步
│   └── packaging/                    # ABI、装载与公开制品
├── fixtures/
│   ├── c/
│   ├── cpp/
│   ├── rust/
│   └── kotlin/                       # 可控提供方、barrier、故障注入
├── consumers/
│   ├── c/
│   ├── cpp/
│   ├── rust/
│   ├── android/
│   ├── kotlin-jvm/
│   ├── kotlin-native/
│   ├── swift/
│   ├── arkts/
│   └── dart/                         # E04 同步探针；不扩大主线计数
├── scenarios/
│   ├── boundaries/                   # 单路线、直接方向及反向回调
│   ├── composition/                  # 多桥共享内核与组合关闭
│   ├── project-init/                 # 新工程、IDE 导入与修改后重建
│   └── distribution/                 # 安装、错库、升级和发布形态
├── harness/
│   ├── runners/                      # 真实目标执行
│   ├── barriers/                     # 交错协调，不替代原生故障入口
│   ├── collectors/                   # 日志、资源与清理证据
│   └── isolation/                    # 进程、设备、目录和 watchdog
├── expected/                         # 独立预期或独立参考实现
├── reports/                          # 运行输出；正式证据按候选归档
├── docs/                             # 安全用法、复现与验收说明
└── .github/workflows/                # 平台消费与证据收集
```
<!-- madb-lab-tree:end -->

逻辑案例与平台外壳分离。目录名不是封闭语言枚举；新增运行时增加消费者，新增提供方按需要增加 fixture。每个真实消费者使用自身构建与运行环境，公共 harness 不代替被测语言的真实调用。实现语言、构建清单与目标依赖随相应配置固定，不强制将所有消费者塞进同一个构建根。

| 目录 | 负责内容 | 禁止混入 |
|---|---|---|
| cases | 问题 ID、适用配置、输入、预期引用及失败条件 | 从当前输出反推期待值 |
| fixtures | 真实提供方和仅测试可用的控制/观察点 | 用生产规则引擎同时实现被测行为与 oracle |
| consumers | 从公开候选安装、编译和调用 SDK | MadB 私有 crate、作者本机生成目录或缓存 |
| scenarios | 案例组合、操作顺序和交错安排 | 第二套重复问题目录或认证状态 |
| harness | 调度、隔离、超时、收集与清理 | 把强杀进程当作 SDK 正确取消 |
| expected | 独立推导的结果、状态与资源后条件 | 复用同一生成器/生产状态机自证正确 |
| reports | 绑定候选、profile、案例、环境与 Lab revision 的观察 | 无身份的“通过”或用历史结果替代本次执行 |

普通报告、临时工程、下载缓存和设备日志与手写案例分离，默认不进入源码提交；需保留的验收证据按固定候选归档、脱敏并记录摘要。golden 只证明形状，行为断言由独立 expected 负责。跨仓库通过已版本化的公开格式协作，不建立私有源码依赖；公开格式的编码复用不等于复用生产规则作为预期。

新增语言执行[扩展验收](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/validation/05-language-onboarding.md)，扩展声明与实际认证分开记录。初始化场景调用候选 MadB 和模板，在新目录创建工程后执行[IDE 验收](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/validation/06-project-initialization.md)，记录导入、源码变更后重建、运行及承诺的调试能力；不预先修补被测工程。

Lab 的 Agent 按[共同开发规范](../engineering/07-agent-development.md)执行；根 AGENTS.md 强调公开候选消费、独立 expected 和真实报告，不直接复制工具仓库的私有实现规则。共享依据使用固定版本的可获取文档，不能依赖作者机器路径；失败不能通过更新预期或缺设备降级来伪装为成功。

## 通用测试能力模型

SampleEngine 提供下列独立场景，避免借用聊天、账户等项目业务概念：

| 能力 | 验证目的 |
|---|---|
| echo/snapshot | 类型、空值、变体、字符串、身份与独立值 |
| checksum(bytes) | 二进制、长度、数值范围和复制成本 |
| openSession/close | 创建、父子资源、准入和关闭 |
| processAsync | 原生延迟、取消、失败、结果所有权 |
| observeState/emitEvent | 状态合并、事件顺序、队列和停止 |
| HostStore callback | 反向调用、同步/异步完成、受理阶段 |
| foreignFutureCompletion | 完成调用后注入抛错，观察一次完成、结果交接与释放 |
| publishedApiConsumer | 通过发布形态实际调用全部承诺接口；发现 unavailable 占位与缺依赖 |

原生 fixture 暴露仅测试可用的 barrier、资源计数器和故障注入点。计数由独立观测或测试专用构建取得，正式 API 不为了测试泄露内部对象。集成测试同时覆盖未插桩 Release 候选，避免插桩掩盖真实问题。

## 执行与依赖

测试锁包含 MadB revision/version、包摘要、后端与运行时、Lab revision、目标环境。一般流程：解包候选 → 构建临时消费工程 → 运行 → 采集证据 → 清理。不能引用 MadB 仓库的私有 crate 或本机生成缓存完成正式验收。

开发阶段可使用源码候选，但必须先构建成与发布形态相同的包，再交给 Lab。两个仓库无需锁步提交；兼容测试协议保证旧工具版本可以继续被复现验证。

Rust↔C 首链建立两个真实消费者：C 消费 Rust 导出库，Rust 消费 C 库；回调另验，不能代替第二个直接方向。作者声明、生成接口、profile/锁、fixture、独立预期和候选包按[首链资产](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/delivery/04-design-readiness-and-first-route.md)落地。C09/C10 在 S1 提供首链所需能力，S5 再完成全矩阵收口；只通过一个字符串成功样例不满足 C05。

## 平台配方的独立消费

- Android 使用分离的 shared KMP、可选 native library 和 app/测试模块。预构建 `.so` 与需要 `externalNativeBuild` 的配置分别验收；公开 SDK 的消费者只声明包依赖，不修补发布包。
- Maven 测试将官方 Kotlin 和 CPF 候选发布到隔离仓库，再由各自干净工程按独立 GAV 解析；检查根 metadata、目标变体、错坐标及仓库内容互不覆盖。
- Swift 消费端分别覆盖 SKIE 本机构建、可分发 framework、Swift C++ direct-source 与 C/ObjC++ 包装；构建系统和反向范围不同，使用不同 profile。
- ArkTS 消费端区分 napi-ohos 主线和 UniFFI ArkTS beta 实验后端。正式应用 SDK、编译 sysroot 和实际设备单独记录；没有设备的脚本只编译成功时，不产生设备运行结果。

这些场景复用公共问题预期，保留平台专用入口；模板/包的生成内容不能成为唯一断言来源。

## 并发与设备隔离

测试进程、设备和临时目录独立分配。每次测试记录启动、结束和清理状态；退出后的后台工作或未回收引用视为证据。死锁测试使用独立进程与 watchdog，超时能终止该测试进程，但不能把“杀死进程”解释为 SDK 成功取消了原生工作。

UI 测试分别验证前后台、页面隐藏/销毁、重复进入、输入法组合态和列表身份。不能只验证 ViewModel 数值变化就宣称页面生命周期正确。

## 作为示例库使用

每个案例有一页短说明：解决什么问题、依赖什么、怎样运行、预期输出、需要保留的业务语义。演示只使用推荐的安全 API；故意不安全的负例隔离在测试目录并标注失败预期。

维护者可以从案例页回到问题编号和契约；普通开发者可以复制安全用法，而无需了解底层 context 和句柄细节。

## 明确的交错入口

fixture 至少能暂停“源端取得 context 后”“执行器已入队但未执行”“结果已 resume 但消费端未恢复”三个时刻。分别观测源端持有、队列票据、用户回调与结果资源；一个 live-count 不足以区分提前释放和遗漏收尾。组合应用 fixture 提供测试专用的实例身份，识别两个桥各建一套内核的问题。详细步骤与独立预期见[CRIT 场景](https://github.com/changyue1053/MadB/blob/bd2fc28dca8e72995ee9bce6330c6b37ad8b557d/docs/validation/08-critical-scenarios.md)。
