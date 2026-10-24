# MadB-Lab

MadB 的独立消费验证与解决方案工程。当前为 C01 仓库基线；没有已运行的跨语言用例、候选 SDK 或认证结果。

使用 Python 3.14.4，在仓库根运行：

```sh
python3 scripts/check.py
```

首期检查仅使用 Python 标准库，不需要 MadB 源码、Cargo 私有 crate、Node 或开发者缓存。检查必要规范的固定版本/摘要、仓库路径隔离，并运行其拒绝规则的正反例；这不是 FFI 或设备验收。

[Agent 入口](AGENTS.md)、[贡献方法](CONTRIBUTING.md)、[固定规范引用](docs/reference/README.md)说明当前任务及依据。根目录不预先生成空消费者或虚构 tool.lock；C02 定义正式格式，C05/C09 引入真实候选与消费者。

## Quick start

With Python 3.14.4, run `python3 scripts/check.py` from an independent checkout. The C01 baseline has no external Python dependencies and does not require the MadB source tree. No SDK behavior is certified by this command.

See [LICENSE](LICENSE) and [third-party scope](THIRD_PARTY.md).
