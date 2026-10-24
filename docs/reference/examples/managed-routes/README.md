# C06 四路线公开候选复现

本指南使用仓库现有 CLI，从作者安装工具开始，经过锁定依赖、冻结构建与打包，再交给独立 MadB-Lab 消费。当前适配器面向 C06 的固定 SampleEngine 接口与语义；它不是任意 Kotlin/Rust 项目的自动发布器。

**C06 整包验收仍在进行。** 当前状态以[任务目录中的 C06](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/catalog/implementation-plan.json)为准，过程和未完成项见[C06 记录](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/docs/reviews/2026-10-24-c06-kotlin-swift-rust.md)。本指南、局部成功和产出 candidate 都不代替四路线的必需验收。

## 配置与平台范围

| 候选目录 | 直接路线与绑定后端 | 主要公开 SDK 文件 |
|---|---|---|
| `kotlin-jvm-rust` | Kotlin/JVM → Rust；UniFFI 0.32.2 及受管补丁 | `sdk/*.jar`、`dependencies/*.jar`、`include/*`、`lib/*.dylib` |
| `kotlin-native-rust` | Kotlin/Native → Rust；Gobley 0.3.7 / UniFFI 0.29.4 及受管补丁 | `klib/*.klib`、`dependencies/*.klib`、`include/*`、`lib/*.dylib`；原生提供方动态链接 |
| `swift-rust` | Swift → Rust；UniFFI 0.32.2 及受管补丁 | `swift/*.swift`、`include/*`、`lib/*.dylib`；Swift 源码在消费端编译 |
| `swift-kotlin` | Swift → Kotlin/Native；ObjC 导出 + SKIE 0.10.15 | `framework/MadBSkie.framework`、`swift/MadBSkieConcurrency.swift` |

每个候选都独立包含 `candidate.json`、`identity.json`、profile、lock、工具链身份、构建证据及许可。选择与消费配置匹配的一份 SDK；这些目录不是可混用的库搜索路径。主线 SKIE 配置不包含 X01 的 KMP-NativeCoroutines 扩展。

当前构建与运行范围是 **macOS Arm64、`aarch64-apple-darwin`、未插桩 Release**。`deployment_target=14.0` 是编译/链接设置，**不表示在 macOS 14 上实际运行通过**；运行系统以本次工具观测和 Lab 报告为准。桌面 JVM 不代表 Android，macOS 不代表 iOS 真机/模拟器、Linux、Windows 或鸿蒙。

所需工具采用精确锁定版本，不按“高于最低版本即可”放行：

- 外部环境：Python 3.14.4、Rust 1.99.1；完整仓库检查另需 Node.js 26.8.2。
- Apple：Xcode 27.0（27A266a）、Swift 6.4、SDK 27.0（26A425），由开发者预先安装并选定；宿主系统必须能运行该工具链。
- 受管安装：Temurin JDK 21.0.10+7、Gradle 9.7.1、Kotlin/JVM 与 Kotlin/Native 2.4.20，以及锁定的 Native 编译器依赖。
- Kotlin/Swift 运行依赖、SKIE 插件、UniFFI/Gobley 源码和补丁均按提交内的锁与 receipt 校验。

完整来源、摘要、安装边界及 Python 运行时隔离见[工具链说明](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/adapters/toolchains/kotlin_rust/README.md)与[固定工具配方](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/adapters/toolchains/kotlin_rust/toolchain.json)。不同机器的实际工具镜像与运行库身份会进入 profile，不能仅凭版本字符串视为同一配置。

## 1. 准备固定作者检出与工作目录

检出包含这些 C06 入口的固定 MadB 提交，按[根 README](https://github.com/changyue1053/MadB/blob/0daf56372c721059be5cc49f80857dd79941cf9d/README.md#开发环境)创建 `.venv` 并安装锁定开发依赖。在 MadB 仓库根执行后续作者命令。正式构建要求生产者检出干净；安装、候选与报告目录放在仓库之外。

```sh
git rev-parse HEAD
git status --porcelain

# 替换为自己选择的新绝对路径；下方各安装/输出子目录必须尚不存在。
MADB_WORK=/absolute/path/to/new-c06-work
mkdir -p "$MADB_WORK"
```

下载与源码构建发生在显式安装阶段。正式 SDK 构建使用已经验证的离线依赖，不从开发者的 Gradle/Konan/Cargo 缓存推断缺失材料。

## 2. 安装编译器、绑定后端与 Maven 依赖

```sh
.venv/bin/python scripts/install_managed_tools.py \
  --root "$MADB_WORK/managed" \
  --cache "$MADB_WORK/source-cache"

.venv/bin/python scripts/install_managed_backends.py \
  --root "$MADB_WORK/backends"

.venv/bin/python scripts/install_managed_tools.py \
  --root "$MADB_WORK/runtime-dependencies" \
  --maven-lock adapters/toolchains/kotlin_rust/runtime-dependencies.json \
  --cache "$MADB_WORK/source-cache"

.venv/bin/python scripts/install_managed_tools.py \
  --root "$MADB_WORK/skie-maven" \
  --maven-lock adapters/toolchains/kotlin_rust/skie-dependencies.json \
  --cache "$MADB_WORK/source-cache"
```

后端安装器默认安装 UniFFI 与 Gobley，生成 `backends/uniffi-tools.json`、`backends/gobley-tools.json` 和各自安装目录。只准备一个后端时可使用 `--backends uniffi` 或 `--backends gobley`；SKIE 单线不需要这两个后端。安装失败保留现场与状态记录，修正原因后换新目录；不覆盖或把部分安装登记为成功。

工具 receipt 绑定源码归档、受管补丁、实际二进制和声明解析器的作者源码闭包。修改相关源码、锁或补丁后，陈旧安装会被拒绝，应重新安装；不能手改 receipt 以继续构建。

## 3. 准备 Rust 离线依赖

```sh
.venv/bin/python scripts/prepare_managed_dependencies.py \
  --output "$MADB_WORK/cargo-dependencies" \
  --uniffi-tools "$MADB_WORK/backends/uniffi" \
  --gobley-tools "$MADB_WORK/backends/gobley" \
  --archive-cache "$MADB_WORK/crate-archives"
```

输出是 `cargo-dependencies/vendor/` 与邻接 `receipt.json`。两个版本分别在临时源码副本中派生受管补丁锁，再执行 locked vendor；仓库内的 canonical `Cargo.lock` 保持不变。共享包必须字节一致，实际 vendored 源码必须匹配锁定的 crates.io 归档；归档缓存同样逐次校验。

## 4. 从冻结输入构建四个公开候选

```sh
.venv/bin/python scripts/build_managed_routes.py \
  --output "$MADB_WORK/candidates" \
  --managed-root "$MADB_WORK/managed" \
  --runtime-dependencies "$MADB_WORK/runtime-dependencies" \
  --maven-repository "$MADB_WORK/skie-maven" \
  --cargo-vendor "$MADB_WORK/cargo-dependencies/vendor" \
  --uniffi-tools "$MADB_WORK/backends/uniffi" \
  --gobley-tools "$MADB_WORK/backends/gobley"
```

省略 `--variants` 会在同一次工具观测下生成四个候选目录。该入口执行真实声明读取、绑定生成、compile/link/run 与 package，复用 C04 冻结端口；显式 prepare 只确定后续输出身份，真正接受的结果由受管执行重新产生并核验。

Rust 提供方、SKIE framework 和适用的原生消费探针使用声明过的、按输入身份寻址的受管工作区。每次持有独占锁后冷构建，工作区身份绑定源码、profile、工具/依赖与构建配方，保留正常 UUID。这样编译器内部的路径身份可以稳定复现；C04 仍重新执行并比较实际字节，差异会阻断提交。受管编译目录和产物输出目录由工具分别管理。

C06 为每个工具子进程明确设置 900 秒执行预算和 6000 毫秒终止宽限期；外层等待覆盖完整构建图及收尾。超时或无法确认清理时，执行失败并保留现场。这些是构建工具的进程限制；SDK 的操作取消、观察停止和关闭排水继续遵循下文的资源协议。

开发定位可增加 `--variants kotlin-jvm-rust` 等已列出的配置，以及明确的 `--allow-dirty`。这类产物会标记 `provisional`，不能用于正式验收。单线成功也不表示四路线整包通过。

作者交付的是整个 `candidates/`，包含每个候选的文件清单、身份与证据。消费端不需要作者安装的 UniFFI、Gobley、Cargo vendor 或 MadB CLI；编译生成的 Kotlin/Swift API 所需工具与运行依赖仍须具备。

## 5. 在独立 MadB-Lab 检出中消费

选定兼容的固定 Lab 提交，确保 Lab 工作区干净。将完整候选和候选绑定的受管编译器安装交付给消费者；若在另一台机器安装，实际 receipt/库存必须与候选要求一致，不能只提供同版本名称。Lab 不读取生产者源目录，也不重新生成绑定。

在独立 Lab 仓库根运行，下面的绝对路径对应前述输出：

```sh
python3 scripts/check.py --c06 \
  --candidates /absolute/path/to/new-c06-work/candidates \
  --managed-root /absolute/path/to/new-c06-work/managed \
  --output /absolute/path/to/new-c06-work/lab-reports
```

此命令先运行 Lab 自身门禁，再用新消费工程、空 HOME/模块缓存及已校验的工具依赖，分别编译、链接并运行四条路线。缺工具、错误目标、provisional 输入、超时、异常崩溃与必需用例失败均不能登记为通过。开发者可用 Lab 的 `scripts/verify_c06.py --allow-dirty` 做明确的临时验证；正式状态仍以双方固定提交、本次候选身份及全部必需报告为依据。

独立预期和真实消费者见 [MadB-Lab](https://github.com/changyue1053/MadB-Lab)。Lab 的读取、编译、运行证据与生产者的构建证据承担不同责任；候选本身不授予认证资格。

## 安全入口与身份来源

先按固定来源/固定摘要的候选清单校验所有文件，再从**独立、已验证的 `identity.json.profile_digest`** 取得 `expectedProfile`。它可以在应用构建时固定为常量，或从应用信任的交付清单读取。**不能调用已加载库的 `profileIdentity()` / `profile_identity()` 取得期望值再传回同一库**，否则错库会为自己提供“正确答案”。profile 摘要也不是 candidate 摘要或 interface 摘要的别名。

| 配置 | 普通消费者使用的入口 | 与原始构造的差别 |
|---|---|---|
| Kotlin/JVM、Kotlin/Native → Rust | `madb.boundary.openEngine(expectedProfile)` | 先执行版本匹配的 UniFFI ABI/函数 checksum 检查，再进入检查 profile 的构造过程 |
| Swift → Rust | `try openEngine(expectedProfile: expectedProfile)` | 先执行可抛出错误的 `madbCheckAbi()`；原始 UniFFI Swift 初始化路径保留上游不兼容时的 fatal 行为 |
| Swift → Kotlin/Native | `try MadBEngineHandle(expectedProfile: expectedProfile)` | 调用 Kotlin 的受检 `openEngine`，并持有 Swift 消费回调的准入/排水责任；原始 `Engine()` 不等价于该门面 |

SKIE 的 factory 检查 profile；framework 的 ABI、导出符号和身份还须在候选校验、编译链接及独立消费中检查，不能把 factory 说成通用 ABI 探测器。使用 `owner.native` 可以访问原始 Kotlin API，但其停止/关闭只覆盖 Kotlin 侧责任；涉及 Swift `collect` 消费体时，通过同一 owner/订阅门面停止和等待。

以下是实际公开方法的最小生命周期片段，`expectedProfile` 由上面的候选验证流程传入，不在示例里从库读取。

```kotlin
import madb.boundary.openEngine

// JVM 与 Native 分别消费各自候选；从可等待的清理协程调用。
suspend fun consume(expectedProfile: String) {
    val engine = openEngine(expectedProfile)
    // 在此使用 engine 的公开业务方法。
    engine.requestClose()
    engine.awaitClosed()
    engine.destroy()
}
```

```swift
// Swift/Rust：将候选 swift/ 源码与 include/ 模块映射接入消费目标。
func consumeRust(expectedProfile: String) async throws {
    let engine = try openEngine(expectedProfile: expectedProfile)
    engine.requestClose()
    try await engine.awaitClosed()
    // 之后由 Swift ARC 释放包装持有的 native 引用。
}
```

```swift
// Swift/Kotlin：链接 MadBSkie.framework，并编译候选的 Swift 门面。
@MainActor
func consumeKotlin(expectedProfile: String) async throws {
    let owner = try MadBEngineHandle(expectedProfile: expectedProfile)
    owner.requestClose()
    try await owner.awaitClosed()
}
```

这些片段展示正常关闭顺序；业务成功、失败、页面退出和调用任务取消时，都要由实际 owner 安排清理。已经取消的任务不能被当成可靠的等待执行器；清理需进入仍可执行/等待的作用域，失败或超时也不能记成已排水。

## 取消、关闭与页面责任

| 意图 | 明确调用或责任 |
|---|---|
| 取消一次 `await` / 协程等待 | 停止这次等待；不自动等于停止底层 operation、停止观察或撤销副作用 |
| 请求停止业务操作 | 调用 operation 的 `requestCancel()`；宿主回调仍必须有界返回，不能假定同步回调可被强制抢占 |
| 停止一个观察 | 调用订阅 `requestStop()`，再等待 `awaitStopped()`；Kotlin/Rust 包装在排水后由其 owner `destroy()`，Swift 释放相应引用 |
| 关闭共享引擎 | 引擎 owner 调用 `requestClose()` 并等待 `awaitClosed()`；页面只关闭自己拥有的观察，不代替共享 owner 关闭引擎 |
| 释放包装或触发 ARC/GC | 释放后端持有关系；不代替显式业务停止与完成排水，析构不阻塞等待工作结束 |
| 在回调中请求关闭 | 非阻塞请求可以发起；不能同步等待该回调自身或依赖它的引擎排水；直接重入可返回 `WouldDeadlock`，工具不自动证明任意跨线程等待环 |

状态合并、事件队列满、字节/句柄/等待者预算等，以每个候选公开 `runtime-protocol.json` 和工具链中绑定的协议为准；不能把状态流当作不丢事件的业务队列。SKIE 门面传递跨 actor 数据时使用独立值快照，不把任意可变 Kotlin 对象宣称为 `Sendable`。

这是 conformance provider 的公开消费说明。Rust 生产导出与单独的 P03 故障夹具分开；SKIE SampleEngine 的测试辅助出口在候选中明确声明，GC 观察不能替代关闭排水成功。后续产品 SDK 的领域重试、事务补偿和业务 owner 选择仍由 SDK 作者决定。
