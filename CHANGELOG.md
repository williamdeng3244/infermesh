# Changelog

## v0.7.0 — 2026-07-07

Milestone 2 — 硬件效率与规模化度量层，dashboard 换上 instrument-bench 新装：

- **换肤**：v2 设计令牌整体搬运（石墨蓝底 + 信号琥珀 accent + 芯片分类色
  `--c1..--c5`），全部旧组件就地换肤；两个全新页面 **硬件分析**（效率 / 容量 /
  扩展 / 分布四 tab：Roofline、吞吐–延迟前沿 + goodput、多卡加速比、延迟分布）
  与 **A/B 对比**（运行级 Δ% 判级 + 驱动时间线 + 正确性判级）。
- **benchmark 后台 job**：`POST /api/bench/jobs`（进度 / 协作式取消），运行期间
  占用一个准入槽位 —— 基准与线上推理共享并发预算；旧同步端点标记 deprecated。
- **基准 schema v2**：驱动 / 固件 / SDK 指纹、多卡（device_count / parallelism /
  interconnect）、能耗（power_avg_w / energy_j）、分布（percentiles / cv_itl /
  n_requests）、correctness 字段；旧库自动原位迁移，旧行完整可读。
- **芯片规格注册表**：`infermesh/config/chip_specs.json` 预置 s60 / a100 /
  rtx4090 / m3max（标注 datasheet / estimated），`~/.infermesh/chip_specs.json`
  按芯片覆盖；`GET/PUT /api/specs`。这是 MBU / MFU 的分母来源，无需硬件计数器。
- **派生指标纯函数库** `core/derive.py`：percentile（线性插值）、cv、MBU、MFU、
  tok/J、goodput —— 与原型 JS 公式一致到小数位。
- **可选功耗遥测**：后端 ABC 新增 `get_power_w()` / `hw_counters()`（默认
  None）；bench 期间 1 Hz 采样聚合 power_avg_w / energy_j；自研卡后端实现两个
  方法即可点亮能耗指标，控制面零改动。
- **多卡基准**：`devices` + `parallelism`；数据并行 = 每卡独立子 run（各占一个
  准入槽位、独立入库），张量并行 = 整组一个 run（vLLM 后端内映射
  `--tensor-parallel-size`）；互联 best-effort 探测（nvidia-smi topo / 规格表）。
- **并发扫描**：`mode:"concurrency_sweep"` + levels + window —— 每级恒定在途、
  逐请求记录 TTFT 与 ITL 序列，child run 入库（batch_size = 并发级），parent 汇总
  吞吐–延迟前沿；新设置 `slo_p99_ttft_s`（goodput 读侧按当前 SLO 现算，不落库）。
- **数值正确性 harness**：固定 20 条 prompt（多语言 / 代码 / 数学 / 长依赖）×
  离线 fp16 贪心参考集 → token 级一致率、首个分歧位置、可选 top-20 logit KL，
  判级 pass ≥0.99 / warn ≥0.95 / fail。`scripts/gen_reference.py` 在有 CUDA 的
  机器上生成参考集（绝不在 GCU 节点上跑）；仓库携带 mock 参考集供 CI 端到端。
- **读侧分析 API**（5 s TTL 缓存，全部只读现算）：`/api/analysis/efficiency`、
  `/frontier?chips=&slo=`、`/scaling?model=&quant=`、`/timeline?chip=&metric=`
  （按 driver_version 分组、相邻回归 >1% 标红）与 `/api/compare?a=&b=`
  （±compare_threshold_pct 判级，新设置项）。
- 测试 138 → 198 全绿；新增 i18n 覆盖检查与零外链检查随 CI 守护。

## v0.6.0 — 2026-07-02

Milestone 2 设计包（仅文档与版本号，无运行时变更）：

- `docs/design/console-redesign-v2.html` — 控制台重设计原型：新增「硬件分析」
  （效率/容量/扩展/分布四 tab：MBU/MFU + Roofline、吞吐–延迟前沿与 goodput、
  多卡张量并行扩展效率、p50–p99.9 分位与 ITL 直方图）与「A/B 对比」
  （九指标 Δ%、驱动/SDK 回归时间线、数值正确性表）
- `docs/review/code-review-v0.4.0.zh.md` — 并发与 IO 路径评审：3×P0、4×P1
- `docs/design/design-and-porting-notes.zh.md` — 设计令牌与三步移植路径
- `docs/milestones/milestone-2-claude-code-prompt.zh.md` — Milestone 2 执行计划（Commit 0–10）
