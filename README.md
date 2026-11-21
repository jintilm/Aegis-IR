# Aegis-IR

[中文](README.md) | [English](README.en.md)

**面向 LLVM IR 的确定性保护与工程评测。**

在启用代码保护前，测量程序正确性、代码体积、运行开销和构建成本，让保护策略有可复现的工程依据。

[快速开始](#quick-start) · [保护一个模块](#protect-a-module) · [发布门槛](#release-gate) · [Aegis-Bench](#aegis-bench) · [隔离机制](#isolation) · [验证证据](#evidence) · [文档](#documentation)

![版本](https://img.shields.io/badge/version-0.4.1--alpha-blue)
![LLVM](https://img.shields.io/badge/LLVM-23.x-6f42c1)
![平台](https://img.shields.io/badge/platform-Linux%20x86--64-lightgrey)
![任务格式](https://img.shields.io/badge/task%20schema-v4-green)
![许可证](https://img.shields.io/badge/license-Apache--2.0%20WITH%20LLVM--exception-blue)

> [!IMPORTANT]
> 项目目前处于 Alpha 阶段，用于研究代码保护及其工程成本。现有测试和评分卡验证语义保持与开销，不代表已经证明抗逆向效果、生产环境平均性能或对专业分析人员的抵抗能力。

<a id="what-this-is"></a>

## 项目组成

| 组件 | 职责 |
|---|---|
| **Aegis-Bench** | 主体评测框架：正确性、`.text` 体积、配对 p95、构建时间评分，以及实验编排、断点恢复、审计和隔离 |
| **Aegis-IR 插件** | 基于 LLVM New Pass Manager 的配套保护插件：按策略注入诱饵、虚假控制流和控制流变换 |
| **[Aegis-adapters](https://github.com/jintilm/Aegis-adapters)** | 独立仓库中的模型适配器：连接 OpenAI 兼容接口，供可选的模型实验使用 |

项目采用“先测量，再选择策略”的开发方式：

- 常规构建、测试和发布不调用大语言模型，也不需要 API 密钥。
- 不支持的保护请求会明确报错，避免策略声称已保护而实际被跳过。
- 在优化后检查保护结构是否仍然存在，并用差分执行检查程序结果。
- 公开的性能与效果表述必须对应报告，并注明任务、版本和适用范围。

<a id="at-a-glance"></a>

## 能力概览

| 项目 | 当前状态 |
|---|---|
| 公开任务 | 12 个，分为 6 个 `core` 和 6 个 `exploratory` |
| 保护等级 | Level 0–3 |
| 差分工作负载 | 小型回归样例，以及每次调用至少完成 1 MiB 工作量的代表性算法样例 |
| 发布检查 | 8 个 CTest 目标，包含两套无需模型的工程评分卡 |
| 构建采样 | 各配置交错进行 3 次独立构建，取中位数 |
| 隔离方式 | 独立进程、Landlock、seccomp、私有网络命名空间，以及可选的逐单元容器 |
| 加固检查 | ASan/UBSan、策略解析器 libFuzzer、Clang Static Analyzer |
| 发布产物 | 可复现归档、SHA-256、CycloneDX SBOM、cosign 无密钥签名 |
| 已发布版本 | [`v0.4.1-alpha`](https://github.com/jintilm/Aegis-IR/releases/tag/v0.4.1-alpha) |

`main` 分支可能包含尚未发布的改动。历史报告只描述其记录的提交，不自动代表当前工作区的结果。

<a id="quick-start"></a>

## 快速开始

推荐使用仓库提供的 Linux 开发镜像。宿主机需要 Git 和 Docker；下面的宿主命令使用 Bash 语法。

```bash
git clone https://github.com/jintilm/Aegis-IR.git aegis-ir
cd aegis-ir

docker build -f docker/dev.Dockerfile -t aegis-ir-dev docker/
docker run --rm -it -v "$PWD:/src" -w /src aegis-ir-dev
```

进入容器后，配置、编译并运行测试：

```bash
export LLVM_DIR="$(llvm-config-23 --cmakedir)"
cmake -S . -B build -G Ninja -DLLVM_DIR="$LLVM_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure
```

发布要求全部 8 个 CTest 目标通过。性能检查会受宿主负载影响；失败时应保留原始报告，检查环境和测量条件。网络命名空间测试还依赖宿主权限，缺少所需能力时会跳过相关检查；具体条件见[隔离文档](docs/isolation.md)。

镜像固定 Ubuntu 24.04 基础镜像摘要，并校验 `llvm.sh` 安装脚本的 SHA-256。LLVM 版本与本机安装方式见[开发环境](docs/dev-environment.md)。Windows 用户可通过 Docker Desktop 的 Linux 容器运行；使用 Git Bash 时，为上述 `docker run` 加上 `MSYS_NO_PATHCONV=1` 前缀以避免路径转换。

除特别注明在宿主机运行的步骤外，以下涉及编译器、`opt` 或 Bash 脚本的命令均在该 Linux 环境中执行。各节命令默认从仓库根目录开始，除非代码块显式切换目录。

<a id="protect-a-module"></a>

## 保护一个模块

### 1. 生成前端 IR

保护变换必须在内联等优化之前运行：

```bash
clang++-23 -O2 -Xclang -disable-llvm-passes -S -emit-llvm \
  examples/demo.cpp -o build/demo.ll
```

### 2. 检查策略适用性

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-lint' \
  -disable-output build/demo.ll
```

`aegis-lint` 会列出被选中的函数、能否应用保护、不支持的原因及修复建议。对于可平坦化的 Level 3 函数，还会输出循环数量、最大循环深度、PHI 节点和跨块值数量，帮助安排成本测量。这些是静态结构提示，不是实际热点分析，也不会自动调整策略等级。

### 3. 应用保护并验证

Level 1 流水线：

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,default<O2>,aegis-verify' \
  -S build/demo.ll -o build/demo.protected.ll
```

策略选择 Level 2 或 Level 3 时，需要加入控制流变换 `aegis-cff`：

```bash
opt-23 -load-pass-plugin=build/lib/AegisPass.so \
  -passes='aegis-policy<policy=examples/aegis-policy.json>,aegis-decoys,aegis-cff,default<O2>,aegis-verify' \
  -S build/demo.ll -o build/demo.protected.ll
```

随后按相同目标平台和 ABI 编译保护后的 IR。流水线顺序是必要条件；跳过保护步骤或让优化器移除必需结构，会使验证失败。明确的空策略或全 Level 0 策略可以作为无保护流程运行。

策略字段与限制见[策略参考](docs/policy.md)、[诱饵变换](docs/decoys.md)和[控制流变换](docs/controlflow.md)。例如，当前 Level 3 会提前拒绝动态或非入口 `alloca`、C 可变长数组等尚未支持的结构。

<a id="protection-profiles"></a>

## 保护配置

| 配置 | 用途 | 发布角色 |
|---|---|---|
| `baseline` | 原始行为基准 | 对照 |
| `release` | 无保护、去符号版本 | 对照 |
| `release-opt` | 经过相同 `opt` 优化流程，但不应用 Aegis 变换 | 小型评分卡基准 |
| `aegis-standard` | Level 1 诱饵 | 默认发布配置 |
| `aegis-research` | Level 2 输入相关分支与虚假边 | 研究观察，不作为发布门槛 |
| `aegis-flattened` | Level 3 基于 volatile 状态的控制流平坦化 | 研究观察，不作为发布门槛 |
| `aegis-debug` | 无保护的 `-O0 -g` 版本 | 调试 |
| `baseline-asan` | ASan/UBSan 检查 | 正确性检查 |

默认配置侧重控制工程开销。Level 3 不建议直接用于热点路径，应先测量目标函数的实际成本。策略的 `level` 数字表示本插件的变换等级，不等同于[威胁模型](docs/threat-model.md)中的能力层级。

上表是差分评测配置名；公开二进制恢复任务的制品配置通常使用 `baseline`、`aegis-level1`、`aegis-level2`、`aegis-level3`，以各任务的 `task.json` 为准。

<a id="release-gate"></a>

## 发布门槛

评分卡对默认 `aegis-standard` 配置执行以下预算检查：

| 指标 | 小型样例 | 代表性样例 |
|---|---:|---:|
| 输出不一致 | 0 | 0 |
| Sanitizer / 性质检查错误 | 0 | 0 |
| `.text` 增长 | ≤ 25% | ≤ 30% |
| 配对相对 p95 增长 | ≤ 25% | ≤ 25% |
| 构建时间中位数增长 | ≤ 25% | ≤ 30% |
| 每组独立构建次数 | 3 | 3 |

小型样例以 `release-opt` 为性能基准；代表性样例以自身的 `baseline` 为基准，该配置已包含相同的 `opt` 优化流程。各配置交错采样，减少预热和宿主负载漂移对某一组结果的偏置。

配对 p95 先比较同一用例在保护版与基准中的平均耗时，再对这些比值取第 95 百分位，不能用两组独立 p95 的比值替代。报告记录 `runtime_baseline_profile` 和逐用例采样；基准不一致或缺少完整配对测量时，评分卡拒绝通过。

生成两套报告并评分：

```bash
python3 tests/differential/run.py \
  --plugin build/lib/AegisPass.so \
  --report build/differential-report.json

cd tools/aegis-bench
python3 -m aegis_bench scorecard \
  --differential ../../build/differential-report.json \
  --budgets ../../experiments/protection-budgets.json \
  --out ../../build/scorecard

python3 ../../tests/differential/run.py \
  --plugin ../../build/lib/AegisPass.so \
  --fixture-dir ../../tests/differential/suites/representative \
  --profiles ../../tests/differential/suites/representative/profiles.json \
  --fuzz-cases 40 \
  --report ../../build/representative-differential-report.json

python3 -m aegis_bench scorecard \
  --differential ../../build/representative-differential-report.json \
  --budgets ../../experiments/protection-budgets-representative.json \
  --out ../../build/scorecard-representative
```

输出包含 `scorecard.json` 和 `scorecard.md`。旧报告若缺少新的基准标记，需要重新采样后才能用于当前门槛，已发布的历史报告应保持原样。预算与测量限制见[工程评分卡文档](docs/protection-scorecard.md)。

<a id="aegis-bench"></a>

## Aegis-Bench 评测框架

运行不依赖模型的实验，检查任务内容、恢复行为和审计结果：

```bash
cd tools/aegis-bench
python3 -m aegis_bench check --tasks-root ../../benchmarks/tasks-public
python3 -m aegis_bench campaign --config ../../experiments/offline-smoke.json
python3 -m aegis_bench audit ../../bench-out/offline-smoke \
  --experiment ../../experiments/offline-smoke.json
```

主要能力包括：

- 任务格式 v4，明确区分 `core` 与 `exploratory`。
- 内容哈希、隐藏用例、性质检查与差分评分。
- 多配置实验编排、交错顺序、原子检查点、断点恢复和独立审计。
- 框架管理的工具代理（tool broker）、Oracle 查询计数与可选的模型 token 计量。
- 经校验的私有制品快照、读取时输出限额、取消执行及资源清理。
- 进程与容器 worker，以及报告中的 Wilson 区间和来源信息。

单次筛选与多次比较是不同级别的证据。目前只有 `packed-record-v1` 对两个试验模型均有 N=5 校准记录；N=1 结果不能写成 N=5 证据。

更多说明：[评测工具手册](tools/aegis-bench/README.md)、[评测协议](docs/benchmark-protocol.md)、[实验编排与审计](docs/campaigns.md)。

<a id="isolation"></a>

## 隔离机制

| 模式 | 适用范围与边界 |
|---|---|
| `in-process` | 同进程执行，仅用于调试与可信离线适配器 |
| `process` | 每个单元启动新 worker，仅传递工作区视图，可启用 Landlock、seccomp 与私有网络命名空间 |
| `container` | 每个单元使用非 root 容器，只读根文件系统、关闭网络、移除能力，并设置资源限制和明确挂载 |

工具代理执行和反汇编使用经 SHA-256 校验的私有制品快照。worker 工作区中的文件副本可供观察，但不会作为可信代理的执行目标；Oracle 模式直接调用受计数与预算限制的服务。停止任务时先取消在途执行，再汇总计数并清理快照。

容器模式仅挂载工作区、单次运行的传输目录、只读框架与适配器目录，以及 broker/meter 的 Unix socket。运行真实容器烟测需要可用的 Docker 守护进程，在能访问该守护进程和源码目录的宿主机上执行：

```bash
python3 tests/container/run_smoke.py \
  --runtime docker --image aegis-ir-dev --user 65534:65534
```

进程超时与输出上限不能替代完整沙箱。适配器 worker 的隔离也不代表评分器已独立容器化；实际信任边界见[隔离文档](docs/isolation.md)和[适配器契约](docs/reference-adapter.md)。

<a id="evidence"></a>

## 验证证据与发布

| 证据 | 位置 |
|---|---|
| 已发布版本 | [`v0.4.1-alpha`](https://github.com/jintilm/Aegis-IR/releases/tag/v0.4.1-alpha) |
| 发布工作流 | [工作流源码](.github/workflows/release.yml) · [历史发布运行](https://github.com/jintilm/Aegis-IR/actions/runs/43695572417) |
| 已入库的版本化完整验证报告 | [`harness-validation-v0.4.0-alpha`](docs/reports/harness-validation-v0.4.0-alpha/README.md) |
| 包含 LTO 的外部 C 工作负载 | [`external-tiny-aes-c-2385675`](docs/reports/external-tiny-aes-c-2385675/README.md) |
| 所有报告与适用范围 | [报告索引](docs/reports/README.md) |
| 公开结论及证据对应关系 | [结论清单](docs/claims-ledger.md) |

发布流程配置了构建与测试、生成 SBOM、为归档和 `SHA256SUMS` 签名、验证签名及发布 GitHub Release。打包阶段若无法创建测试日志或 CTest 返回失败，会终止流程。

生成新的本地验证报告时，在可访问 Docker 的宿主机 Bash 中，从干净的仓库根目录执行。脚本会自行启动带有所需权限的开发容器：

```bash
bash scripts/release-report.sh harness-validation-local
```

每份报告记录源提交和工作区状态。历史报告不覆盖新提交，也不能替代当前代码的验证。

<a id="compatibility"></a>

## 兼容性

当前支持环境：

- Linux x86-64。
- LLVM/Clang 23.x，推荐使用项目提供的开发镜像。
- CMake ≥ 3.20、Ninja、C++17。
- Python 3.10+；评测框架仅依赖标准库。

插件不支持 Windows/macOS 原生构建，也不保证其他 LLVM 主版本可用。多模块回归覆盖普通链接与 LTO，外部兼容性样例也包含 `-flto` 配置；这些覆盖不等于支持任意项目的全部 LTO 组合。更详细的平台说明见[兼容性文档](docs/compatibility.md)。

<a id="development-checks"></a>

## 开发与检查

常规测试：

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure
```

8 个 CTest 目标分别为 `aegis-policy`、`aegis-decoys`、`aegis-controlflow`、`differential`、`differential-representative`、`protection-scorecard`、`protection-scorecard-representative` 和 `aegis-bench`。

其他加固检查与打包回归：

```bash
bash scripts/sanitizer-check.sh
bash scripts/fuzz-policy.sh
bash scripts/static-analysis.sh
python3 -m unittest discover -s tests/package -v
```

固定版本的外部工作负载需要获取第三方源码，因此独立于 CTest：

```bash
python3 tests/external/run_tiny_aes.py \
  --plugin build/lib/AegisPass.so \
  --report build/tiny-aes-external-report.json \
  --markdown build/tiny-aes-external-report.md
```

贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全问题反馈见 [SECURITY.md](SECURITY.md)。

<a id="optional-model-research"></a>

## 可选的模型实验

真实模型实验用于研究特定条件下的恢复成本，不是常规发布要求。模型适配器位于独立仓库 [Aegis-adapters](https://github.com/jintilm/Aegis-adapters)，提供 OpenAI 兼容接口接入、完整有效配置和配置指纹，并对接本框架的工具、计量与恢复机制。

比较不同保护等级时应使用 `binary` 访问模式。`oracle` 模式只提供行为相同的黑盒接口，无法据此测量静态保护变换的影响。参考适配器的旧 model-only 配置需要迁移为完整 `effective_options()`；直接使用示例文件中的占位值不能启动有效实验。配置生成方法见[适配器契约](docs/reference-adapter.md)。

已有模型试验保存在[报告目录](docs/reports/README.md)。token 计量不完整、样本量不足或成功率未固定时，结果只能在其记录的条件下解释，不能据此宣称降低了恢复成功率或证明普遍有效的抗逆向能力。

<a id="security-posture-and-non-goals"></a>

## 保护边界与非目标

保持程序语义的代码变换只能尝试提高恢复成本，不能让语义永久不可恢复。动态跟踪、白盒分析以及具备源码的分析人员都在本项目明确考虑的限制范围内。

项目不提供以下能力：

- 根据分析环境改变业务结果。
- 导致错误或崩溃的反调试行为。
- 以规避恶意软件分析为目标的功能。
- 对无权保护的软件实施保护。

部署前请阅读[威胁模型](docs/threat-model.md)。客户端混淆不能替代服务端认证、授权或安全的密钥管理。

<a id="repository-layout"></a>

## 目录结构

```text
include/aegis/        公共头文件
lib/                 LLVM Pass 插件
tools/aegis-bench/    评测框架与工程评分卡
benchmarks/          公开任务定义
experiments/         实验与预算配置
tests/               策略、变换、差分、打包与隔离测试
docs/                协议、威胁模型、报告和结论清单
docker/              固定开发环境
.github/workflows/    CI 与签名发布工作流
```

<a id="documentation"></a>

## 文档导航

详细技术文档目前以英文为主。

- [架构](docs/architecture.md)
- [策略参考](docs/policy.md)
- [诱饵变换](docs/decoys.md)
- [控制流变换](docs/controlflow.md)
- [工程评分卡](docs/protection-scorecard.md)
- [评测协议](docs/benchmark-protocol.md)
- [实验编排与审计](docs/campaigns.md)
- [隔离机制](docs/isolation.md)
- [模型适配器契约](docs/reference-adapter.md)
- [发布检查清单](docs/release-checklist.md)
- [发布签名](docs/release-signing.md)
- [公开结论与证据](docs/claims-ledger.md)

<a id="naming"></a>

## 名称说明

`IR` 指 **Intermediate Representation（中间表示）**。本项目与名称相近的 AegisIR 事件响应工具无关。

<a id="license"></a>

## 许可证

Apache-2.0 WITH LLVM-exception，详见 [LICENSE](LICENSE)。
