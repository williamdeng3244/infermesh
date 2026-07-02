# infermesh Milestone 2 — 硬件效率与规模化度量层（Claude Code 执行 prompt）

> 把下面全部内容作为一条消息交给 Claude Code，在 infermesh 仓库根目录执行。工作语言中文，commit message 用英文。

---

你在 infermesh 仓库工作。这是一个硬件无关的 LLM 推理服务平台（Python 3.11+ / FastAPI / hatchling），当前本地版本 v0.5.0，已有 138 个测试全绿。本 Milestone 的目标是加装**硬件效率与规模化度量层**：让基准系统能回答"这块芯片的差距在哪个子系统、驱动哪一版引入了回归、多卡扩展效率如何、数值是否正确"——服务对象是公司自研显卡（GX 系列）的 bring-up 与迭代。

## 不可协商的约束（每个 commit 都必须满足）

1. **控制面纯净**：`infermesh/core/`、`infermesh/api/`、`server.py`、`cli.py` 禁止 import mlx / torch / torch_gcu / 任何 vendor SDK。硬件代码只能在 `infermesh/backends/<name>/` 内，经 `InferenceBackend` ABC + lazy factory 接入。`tests/test_no_vendor_imports.py` 必须始终通过。
2. **环境现实**：部署环境为中国内网 Enflame S60（GitHub/HF 被墙）。任何测试**不得联网**、不得下载模型；需要参考数据的用小型 fixtures 随仓库携带。torch_gcu 会劫持 `import torch` 导致 CPU 推理挂起——不要写"在本机跑 CPU 参考实现"的逻辑。磁盘预算 ~30GB。
3. **不引入新服务**：持久化只用现有 SQLite（`core/community.py`）与 JSON/JSONL。不加 Redis/Postgres/消息队列。
4. **每个 commit 收尾必须跑**：`pytest -q`（全绿，含既有 138 个）、`python -m py_compile $(git ls-files '*.py')`、若改了 dashboard 则提取 `<script>` 跑 `node --check` 并跑 i18n 覆盖测试。
5. 每个 commit 独立可回滚，先写测试或与实现同 commit 提交。

## UI 参考

仓库内 `docs/design/console-redesign-v2.html` 是一个已验证的静态原型（Analysis 四个 tab + Compare 页，含 rooflineSVG / frontierSVG / scalingSVG / timelineSVG / histSVG / bindTTs 等自包含函数与全套中英文案）。Commit 9 直接从中移植前端代码，不要重新发明。

---

## Commit 0 — 前置：benchmark 改为后台 job 并纳入准入门控

现状（v0.4.0 评审确认）：benchmark 路由绕过 admission gate，在 HTTP 请求内同步跑最长 240s。后续的并发扫描（Commit 6）会跑更久，必须先修这个。

- 新建 `core/bench_jobs.py`：内存 job 表 `{job_id, spec, state: queued|running|done|failed|cancelled, progress: {phase, current, total}, result_run_ids, error}`，job 在后台 task 中执行，**通过现有 admission gate 申请槽位**（benchmark 与线上推理共享并发预算，避免互相踩踏）。
- API：`POST /api/bench/jobs` 返回 job_id；`GET /api/bench/jobs/{id}` 查进度；`POST /api/bench/jobs/{id}/cancel` 协作式取消（在迭代边界检查取消标志）。保留旧同步端点一个小版本并标记 deprecated。
- 测试：用 MockEchoBackend 跑一个 2 迭代 job，断言状态机流转与取消路径。

## Commit 1 — 基准 schema v2（驱动指纹 + 分布 + 多卡 + 能耗 + 正确性字段）

- `core/community.py`：加 `schema_version` 表；写迁移函数 v1→v2，全部新列 **nullable**，旧行可读。
- benchmark 记录与社区表新增字段：
  - 驱动指纹：`driver_version`, `firmware_version`, `sdk_version`（string，采集不到就 null，采集方式：backend 自报 → 环境变量 `INFERMESH_DRIVER_INFO` → null）
  - 多卡：`device_count`(int), `parallelism`(JSON `{"tp":n,"pp":n}`), `interconnect`(string)
  - 能耗：`power_avg_w`(float), `energy_j`(float)
  - 分布：`percentiles`(JSON：`{"ttft":{"p50":..,"p90":..,"p99":..,"p999":..},"itl":{...}}`)、`cv_itl`(float)、`n_requests`(int)
  - 正确性：`correctness`(JSON `{"greedy_match":0.992,"mean_kl":0.0031,"ref":"fp16-cpu-precomputed","first_divergence":137}`)
- 测试：携带一个 v1 SQLite fixture，跑迁移后旧行完整可读、新行可写、`PRAGMA user_version`/schema_version 正确。

## Commit 2 — 芯片规格注册表

- 新建 `config/chip_specs.json`（随包分发 + 用户目录可覆盖）：每芯片 `{peak_bw_gbps, peak_tflops_fp16, tdp_w, interconnect}`。预置 s60 / a100 / rtx4090 / m3max 条目（数值标注 source: datasheet/estimated），自研芯片由用户添加。
- `core/specs.py`：加载、合并用户覆盖、校验；API `GET/PUT /api/specs`（PUT 需鉴权，复用现有 api_key 机制）。
- 这是 MBU/MFU 的分母来源——**第一版不需要任何硬件计数器**。

## Commit 3 — 派生指标纯函数库 `core/derive.py`

全部纯函数 + 单元测试（固定向量断言到小数点后 4 位，与原型 JS 实现的公式一致）：

- `percentile(samples, p)`（线性插值）、`cv(samples)`
- `mbu(weight_bytes, tg_tok_s, peak_bw_gbps)` = weight_bytes×tg ÷ (bw×1e9)
- `mfu(params, pp_tok_s, peak_tflops)` = 2×params×pp ÷ (tflops×1e12)
- `tokens_per_joule(tg, power_w)`
- `goodput(frontier_points, slo_p99_s)` → (goodput, concurrency)
- 权重字节数按量化推导：`{fp16:2, int8:1, int4:0.5}` × 参数量，模型参数量从现有 model schema 读取。

## Commit 4 — ABC 可选能力：功耗采样与硬件计数器

- `InferenceBackend` 增加**可选**方法（默认实现返回 None，不破坏现有 4 个 backend）：`get_power_w() -> float | None`、`hw_counters() -> dict | None`。
- bench job 运行期间起一个 1Hz 采样线程（仅当 backend 的 get_power_w 返回非 None），聚合 `power_avg_w` 与 `energy_j`。
- MockEchoBackend 返回合成功率曲线供测试；conformance 测试套件加"可选方法缺省安全"断言。
- 自研卡 backend 未来实现这两个方法即可点亮功耗与 counter 数据——控制面零改动。

## Commit 5 — 多卡基准

- bench spec 支持 `devices: ["gcu:0","gcu:1"]` 与 `parallelism: {"tp": 2}`。
- 两种模式：(a) **数据并行**——每卡独立起一份相同 spec 的子 run（job runner 用线程池，每卡各占一个 gate 槽位）；(b) **张量并行**——整组卡跑一个 run，vllm backend 把 tp 映射到 `tensor_parallel_size`（映射代码只能在 `backends/vllm/` 内）。
- interconnect 采集：NVIDIA 上 best-effort 解析 `nvidia-smi topo -m`（subprocess，在 to_thread 中跑，失败即 null）；其它芯片从 specs 注册表读。
- 记录 `device_count / parallelism / interconnect`。扩展效率不在采集端算，由读侧 API（Commit 8）按 1 卡基线现算。
- 测试：MockEchoBackend 双"设备"数据并行 job，断言产出 2 条 run 且字段正确。

## Commit 6 — 并发扫描模式（吞吐–延迟前沿）

- bench spec 支持 `mode: "concurrency_sweep"`, `levels: [1,2,4,8,16,32]`, `window_s: 30`。
- 每级并发用 asyncio 信号量维持恒定在途请求数，窗口内逐请求记录 TTFT 与 ITL 序列；每级产出一条 child run（percentiles/cv 用 Commit 3 的函数算），parent run 汇总 frontier 数组。
- Settings 新增 `slo_p99_ttft_s`（默认 2.0）；goodput 在读侧按当前 SLO 现算，不落库。
- 测试：Mock backend 3 级小窗口 sweep，断言 child/parent 结构与百分位单调性（p50 ≤ p90 ≤ p99）。

## Commit 7 — 数值正确性 harness

- `fixtures/correctness/prompts.jsonl`：20 条固定 prompt（多语言、代码、数学、长依赖各若干）。
- `fixtures/correctness/ref/{model_id}.jsonl`：**离线预生成**的 fp16 贪心解码参考输出（每条前 128 token 的 token id 序列）。附 `scripts/gen_reference.py` 说明如何在有 CUDA/CPU 的机器上再生成——**绝不在 GCU 节点上生成**（torch_gcu 劫持问题）。仓库先携带 Qwen2.5-7B-Instruct 一个模型的参考集。
- `core/correctness.py`：对被测 backend 逐条贪心解码，计算 token 级一致率、首个分歧位置；若 backend 能返回 logits 则加 mean top-20 logit KL，否则该字段 null。阈值：match ≥ 0.99 → pass，≥ 0.95 → warn，否则 fail（可配置）。
- bench spec 加 `correctness: true` 开关；结果写入 Commit 1 的 correctness 字段。
- 测试：Mock backend 构造一个"完美复读"与一个"第 10 个 token 开始漂移"的假实现，断言判级正确。

## Commit 8 — 读侧分析 API

全部只读、内存 TTL 缓存 5s、走 `asyncio.to_thread` 查库：

- `GET /api/analysis/efficiency` → 每芯片 `{mbu, mfu, tok_j, soak_delta}`（联合 specs + 最新 runs）
- `GET /api/analysis/frontier?chips=&slo=` → 各芯片 sweep 点列 + goodput
- `GET /api/analysis/scaling?model=&quant=` → 按 device_count 分组的加速比/效率（以 1 卡中位为基线）
- `GET /api/analysis/timeline?chip=&metric=tg` → 按 driver_version 分组的中位序列，标记相邻回归（Δ < −1%）
- `GET /api/compare?a=<run_id>&b=<run_id>` → 双 run 全字段 + Δ%，阈值判级（默认 ±2%，settings 可配）

## Commit 9 — Dashboard：Analysis 与 Compare 页

- 从原型 `docs/design/console-redesign-v2.html` 移植：导航两个新条目（analysis / compare 图标已画好）、`P.analysis`（Efficiency / Capacity / Scaling / Distributions 四 tab）、`P.compare`、SVG 构建函数五件套、`bindTTs` 通用 tooltip、全部 ZH 词条（原型里有现成的 `Object.assign(ZH, {...})` v2 块）。
- 数据源从原型的 mock 换成 Commit 8 的 API；保留原型的空态文案（如"任何并发下均无法满足该 SLO（受限于 prefill）"）。
- dashboard 的 localStorage 持久化（语言/主题/筛选状态）在真实版本恢复。
- 提取 `<script>` 过 `node --check`；i18n 覆盖测试必须包含新增键。

## Commit 10 — 文档与总验收

- README 新增"Hardware efficiency & fleet metrics"一节；CHANGELOG。
- 验收清单（全部满足才算完成）：
  1. 全套 pytest 绿（≥ 原 138 + 新增）；no-vendor-imports 绿。
  2. v1 SQLite 经迁移后旧数据完整可读。
  3. Mock backend 可端到端跑：普通 job、双设备数据并行、3 级 sweep、correctness 判级——全程无网络。
  4. `/api/analysis/*` 与 `/api/compare` 返回结构与 dashboard 渲染匹配。
  5. dashboard JS 语法与 i18n 覆盖测试绿。
  6. 控制面 grep 不到任何 vendor import。

## 明确不做（防止范围蔓延）

Prometheus 导出、hub 心跳/fleet 聚合、OOM 边界二分探测、热节流自动检测——这些属于 Milestone 3。本 Milestone 只做"单 hub 内让数据变得可诊断"。
