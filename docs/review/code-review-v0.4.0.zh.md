# infermesh 代码评审报告

**评审对象**：GitHub 公开仓库 v0.4.0（williamdeng3244/infermesh，约 14,700 行 Python）。
**重要说明**：本地 v0.5.0（社区基准库、Performance Explorer、GCU crash guard、下载暂停等）尚未 push，本报告未能覆盖；下述部分问题（如 efsmi 解析）可能在 v0.5.0 中已修复，push 后建议对照复核。

评审重点围绕两条主线：一是当前 S60 单机部署的稳定性，二是未来自研显卡（GX 系列）规模化多机使用时会被放大的问题。

---

## P0 — 会直接造成服务阻塞或数据风险，建议优先处理

### P0-1 模型池锁覆盖了整个模型加载过程

**位置**：`infermesh/core/pool.py` `get_engine()`（约 296–333 行，docstring 中也自述了此行为）。

**问题**：`get_engine` 在持有池锁的状态下执行完整的模型加载。7B 模型在 S60 上加载需要数十秒，14B 更久。加载期间，所有请求——包括访问**已经加载好的其它模型**的请求——都会被这把锁挡住。在多模型常驻的场景下，这意味着任何一次冷启动都会让整个服务停摆几十秒；规模化多机部署时，一台节点上的模型轮换会造成该节点全部流量超时。

**建议**：把加载移出锁外。锁内只做三件事：查缓存命中、给目标模型打 `is_loading` 标记并**预留 estimated_mb 显存额度**、注册一个 `asyncio.Condition`/`Event`。加载在锁外执行；同一模型的并发请求等待该 Condition 而不是重复加载；其它模型的请求正常通过。预留额度可防止加载期间被 LRU 判定"有空闲显存"而并发加载第二个大模型导致 OOM。

### P0-2 `/api/devices` 在 async 路由中同步执行设备枚举

**位置**：`infermesh/api/server.py` 约 652 行；`infermesh/core/devices.py` 中 `enumerate_devices()` 依次以 `subprocess`（timeout=5）调用最多 3 个 CLI 工具（nvidia-smi / efsmi / rocm-smi）。

**问题**：这是在 FastAPI 的事件循环里同步跑最长 ~15 秒的子进程。期间**整个事件循环冻结**：所有 API 请求、所有正在进行的流式输出全部卡住。Dashboard 的 Devices 页每次刷新都会触发一次。

**建议**：`await asyncio.to_thread(enumerate_devices)` 包一层，同时给结果加 3–5 秒 TTL 缓存（设备拓扑几乎不变，dashboard 轮询没必要每次真枚举）。这是一行改动量级、收益极大的修复。

### P0-3 `record_rejection` 每次拒绝都全量重写统计文件

**位置**：`infermesh/core/stats.py` 约 298–304 行。

**问题**：正常的 `record()` 有 `_SAVE_EVERY` 批量落盘节流，但 `record_rejection()` 没有——每收到一次 503 拒绝就完整重写一遍 stats JSON 文件。这正好构成一个放大器：服务过载 → 大量 503 → 每个 503 触发一次全文件磁盘写 → 磁盘 I/O 进一步拖慢服务 → 更多 503。在压测或真实流量尖峰时会自我恶化。

**建议**：让 rejection 走与 record() 相同的批量节流路径；或至少改为"标脏 + 定时器合并落盘"。

---

## P1 — 功能可用但存在明显缺陷，规模化前应修复

### P1-1 benchmark 路由绕过准入门控，且在请求内同步跑完全程

**位置**：`infermesh/api/server.py` 约 730–763 行。

**问题**：基准测试端点不经过 admission gate，直接在 HTTP 请求的生命周期内同步执行（默认配置可达 240 秒）。后果有三：其一，benchmark 与线上推理争抢显存和算力却不受并发控制；其二，240 秒的挂起请求极易被反代/客户端超时切断，结果丢失；其三，无法查询进度、无法取消。

**建议**：改为后台 job 模式——POST 返回 job_id，跑在受 gate 管控的任务里，进度通过轮询端点或 SSE 推送。这也正是新 UI 原型里 Benchmark 页的交互假设（提交后异步跑、完成后 toast + 入库），前后端可以一起对齐。

### P1-2 流式分支的 gate 释放存在泄漏窗口

**位置**：`server.py` 聊天补全路由的流式分支。

**问题**：非流式路径用 `finally` 释放 admission gate，是对的；但流式分支只显式捕获了 `ModelNotFoundError` 和内存类错误——如果在 `return StreamingResponse(...)` 之前抛出**其它任何异常**（如后端初始化失败、参数校验异常），`gate.acquire()` 拿到的名额不会被释放。泄漏若干次后，服务在"看起来空闲"的状态下开始拒绝所有请求，且只能重启恢复。

**建议**：把 acquire 之后到 StreamingResponse 构造完成之间的代码整体包进 try/except，任何异常路径都先 release 再抛。

### P1-3 指标落盘在事件循环内同步执行，且 metrics.jsonl 无界增长

**位置**：`server.py` 约 170–188 行 `_record_metric`；`core/history.py` `_append`。

**问题**：每个请求完成时在事件循环里同步 append 磁盘。单条很快，但高并发下会累积成可感知的尾延迟。另外 `metrics.jsonl` 只在**启动时**截断到 5000 条上限——长期运行的节点（正是生产形态）文件会无限增长。

**建议**：写入改为 `asyncio.to_thread` 或后台队列消费；截断逻辑改为运行期定期执行（如每 N 条写入后检查一次）。

### P1-4 efsmi 输出解析把已用显存记为 0

**位置**：`core/devices.py` `_enflame()` 约 165–187 行。

**问题**：对 efsmi 输出的解析结果是 `mem_used=0`、`mem_free=total`，导致 S60 的显存利用率在 Devices 页恒显示为空。这会直接误导容量决策（池上限、能否再加载一个模型）。v0.5.0 若已修复请忽略；未修复的话，建议按当前 efsmi 版本（2.5.136）的实际输出格式重写解析，并把解析器做成按 `efsmi --version` 分支的结构，为驱动升级留余地。

---

## P2 — 改进项与加固建议

**锁内逐 backend 查询显存**：`pool.py` 的 `_current_used_mb` 在持锁状态下依次调用每个 backend 的 `stats()`——这是 vendor 侧查询，可能慢。建议 backend 自报缓存值或把查询挪到锁外快照。

**Settings API 默认无鉴权**：未配置 api_key 时，`PUT /api/settings` 允许任何能访问端口的人修改 host/port、甚至**设置一个 key 把管理员自己锁在外面**。单机 + SSH tunnel 下风险可控，但公司内网多人环境必须：默认要求鉴权、或至少把改 host/port/key 的操作限制在 localhost，生产建议统一挂反代 + TLS。

**流式取消不会停止后端解码**：客户端断开时只 `task.cancel()` 了 asyncio 任务，backend 线程里的解码循环感知不到，会把整段 decode 跑完——白白占用 GCU。建议在 backend ABC 里加协作式取消信号（如 `should_stop` callable 传入 generate）。

**Enflame 环境下应隐藏 CPU 设备**：torch_gcu 劫持 `import torch` 导致 CPU 推理挂起，这一点你们已经用 GCU-only 处理了。建议在 `devices.py` 层面固化：检测到 enflame 设备时直接不产出 cpu 条目，避免误选。

---

## 面向自研显卡规模化的四条结构性建议

**1. 给基准 schema 加驱动指纹**。在 benchmark 的 system-info 与社区库记录里加入 `driver_version / firmware / sdk_version` 字段。自研卡 bring-up 阶段驱动会频繁迭代，没有这三个字段，你们将无法回答"性能回退是驱动 2.6 引入的还是模型侧的"这类最常见的问题。这是改动最小、对公司价值最大的一条。

**2. 暴露 Prometheus `/metrics`**。现有 JSONL 指标适合单机 dashboard，但多节点集群需要标准拉取端点（QPS、TTFT/TPOT 分位数、队列深度、显存、拒绝数）。有了它，Grafana 告警和容量规划都是现成生态。

**3. hub 心跳 + fleet 视图**。让每个节点向 INFERMESH_HUB_URL 定期上报心跳（版本、设备、已载模型、健康状态），hub 端聚合成机队视图。新 UI 原型的 Devices 页已经画出了这个形态（节点表 + GX-1 样例行），可作为目标形态参考。

**4. Backend conformance 测试套件**。把 `InferenceBackend` ABC 的 8 个方法约定固化为一套硬件无关的一致性测试（加载/卸载幂等、流式取消、显存上报单调性、错误类型契约）。自研卡团队写新 backend 时跑这套测试即可自证兼容，控制面团队不需要介入每次 bring-up——这是"控制面不 import vendor SDK"原则在组织层面的延伸。

---

## 一句话总结

v0.4.0 的架构分层（控制面纯净 + backend 可插拔）是对的，问题集中在**并发边界**上：三个 P0 都是"同步/持锁的慢操作放进了异步热路径"。修完 P0-1/2/3 与 P1-2，单节点就能稳定承受真实并发；再补上驱动指纹与 conformance 套件，就为自研卡的规模化铺平了路。
