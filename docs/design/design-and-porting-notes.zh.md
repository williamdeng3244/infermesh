# infermesh 控制台重设计 — 设计说明与移植指南

配套文件：`docs/design/console-redesign-v2.html`（单文件原型，双击浏览器打开即可，无需服务器、无外部依赖）。

---

## 一、设计立意：从"网页模板"到"测量仪器台"

v0.4.0 的 dashboard 是典型的深蓝底 + 荧光绿 accent 管理后台模板。这次重设计围绕一个核心判断：**infermesh 的本质是一台测量仪器**——它的用户（尤其是自研显卡团队）盯着的是数字、分布和对比，而不是在"用一个网站"。因此：

**配色**：深石墨蓝底座，主 accent 换成信号琥珀 `#FFB224`——示波器/仪表指针的颜色，克制且指向"读数"。芯片用固定的分类色系，跨所有页面一致：S60 琥珀、A100 天蓝 `#38BDF8`、RTX 4090 紫 `#A78BFA`、M3 Max 粉 `#F472B6`、GX-1（自研样例）灰 `#9AA8B6`。用户在 Explorer 里看到一根紫色箱线，不用看图例就知道是 4090。

**数字排版**：所有指标读数使用等宽字体 + `font-variant-numeric: tabular-nums`，像数据手册一样对齐。数字是这个产品的主角，排版要配得上。

**签名视觉元素**：点阵网格测量画布上的分组箱线图 + 悬停读数 tooltip。这是整个产品最有辨识度的一屏，也是给公司展示测试结果时最"专业"的一屏。

**双主题 + 双语言**：右上角即时切换深/浅主题（`data-theme` 属性驱动全套 CSS 变量）与中/英文（默认中文）。i18n 采用与现有 dashboard 相同的思路：英文原文即键，ZH 字典映射，缺键回退英文——并配了一个自动覆盖检查（见第四节）。

**零外部依赖**：无 CDN、无 webfont、无网络请求。这既是 artifact 环境的限制，也恰好符合国内部署（GitHub/HF 被墙）的现实约束——原型即部署形态。

## 二、原型包含什么

左侧导航按职能分四组，共 11 页，全部可点：

**总览**：6 张 KPI 卡（在线节点、已载模型、24h 请求、p50 TTFT、GCU 显存、社区记录数）+ 最近 S60 基准表 + 两张琥珀左边条 Insight 卡（GX-1 int8 提速 32% / S60 仅 fp16 的路线图提示）——这是"帮公司看到可优化点"的直接呈现形式。

**服务组**：Models（模型池视图：已载/pinned/TTL 倒计时/卸载态，池顶显示 41GB ceiling 双段 meter 与 LRU 说明）、Chat（试聊面板，预置回复，标注了接入 `/v1/chat/completions` 的位置）、Logs（着色终端日志，含 422 UnsupportedModelError、TTL 卸载、503 拒绝、下载进度等真实事件形态，可按级别筛选/搜索/Follow）。

**观测组**：Metrics（4 张 sparkline 卡 + 24h 面积图 + per-model 表）、Devices（S60 在线卡含 driver/util/温度、CPU disabled 卡并注明 torch_gcu 原因、A100 离线 ghost 卡，下方是**机队表**——3 个节点，含 GX-1 in-house sample 行，即规模化后的目标形态）。

**基准组**（本次重点）：
- **Run**：配置表单（模型/量化/上下文多选/迭代数/自动发布开关）+ 设备选择卡 + **双语指标参考**（9 个指标各配一句人话解释：TTFT、TPOT、pp、tg、E2E、total throughput、峰值显存、batch、speedup）+ 运行历史。点"开始基准测试"会模拟 3 秒运行并 toast 完成。
- **Explorer**：v0.5.0 Performance Explorer 的完整交互重现。指标/模型下拉 + 量化 chips + 芯片图例 chips（点击增减序列），分组箱线图即时重画（X=上下文 512→8k，Y 轴按指标自动换算刻度与单位），**悬停任意箱体弹出 median/q1/q3/mean/min/max/n 读数表**，下方对比卡随筛选联动（median@2k 大读数 + tg/pp/峰值显存 mini 表）。Copy 与 Export CSV（13 列）都是真实现。
- **Community**：社区基准库。筛选卡（搜模型/芯片/量化/上下文/Min pp/Min tg/排序）+ 结果表，**每行点击展开该次运行的仿真终端原文**（`$ infermesh bench --model ... --device gcu:0` + 结果表 + system 行 + published 确认），带 Copy。

**管理组**：Downloads（源切换 HF / hf-mirror.com / ModelScope，三种状态行：下载中 62% 可暂停、已暂停 41% 可续传/删除、已完成——对应 v0.5.0 的暂停/删除能力）、Settings（服务/池/社区 hub/界面四组，含 INFERMESH_HUB_URL 与 auto-publish）。

**Mock 数据**：种子随机（seed 42），5 芯片 × 3 模型 × 3 量化 × 5 上下文的合法组合（显存不足的组合会像真实系统一样被跳过，如 4090 跑 14B fp16），每组合 6–12 个样本。S60 的数字锚定在你们的真实测量上：Qwen2.5-7B fp16 ≈ 12 tok/s decode、峰值 ~14.5GB、总显存 49.1GB。GX-1 是虚构的自研卡占位样例，参数设定在 S60 与 A100 之间。

## 三、如何移植进真实 dashboard

原型是刻意按"可拆解"写的，建议路径：

**第 1 步 — 样式令牌整体搬运**。`<style>` 里第一段是完整的 CSS 变量系统（`:root` 深色 + `[data-theme=light]` 浅色覆盖）。把它原样放进 `dashboard.py` 的 HTML 字符串顶部，替换旧配色即可让现有页面立刻换肤，风险最低。芯片分类色建议做成 `--c1`…`--c5` 变量并在后端下发芯片→色号的映射，保证新增芯片时前后端一致。

**第 2 步 — 箱线图模块**。`boxStats()`、`niceTicks()`、`boxPlotSVG()`、`bindBoxTT()` 四个函数是自包含的（纯数据进、SVG 字符串出、无框架依赖），可直接拷进现有 dashboard 的 `<script>`，把输入从 mock 的 `exSeries()` 换成 `/api/community/query` 的真实返回。这是 v0.5.0 Explorer 前端最有复用价值的部分。

**第 3 步 — 页面逐个替换**。每个页面渲染器都是 `P.页名 = () => HTML字符串` + 可选的 `mount页名()` 注水函数，与现有 dashboard 的区块结构一一对应，可以一页一页换，不必一次性重写。

**关于单文件 vs build-step**：dashboard.py 目前是 1,197 行 r-string，加上新 UI 会到 ~2,500 行。可以继续单字符串（保持零构建的部署简单性），也可以拆成 `dashboard/` 目录下的 .html/.css/.js 由 hatchling 打包进 wheel、启动时读取拼接。建议先单字符串跑通，体量再涨时用 30 行的拼接脚本过渡，不必上前端工具链。

**localStorage 加回**。原型因 artifact 环境限制未用 localStorage；真实 dashboard 应恢复：语言、主题、Explorer 的筛选状态（metric/model/chips/quants）都值得持久化。搜索 `setLang` 与 `toggleTheme` 两个函数，各加一行读写即可。

**与 v0.5.0 对齐**。原型对 Explorer/Community 的字段假设来自你的描述（median/q1/q3/mean/min/max/n、submitter=hostname+label、terminal 原文存储）。push v0.5.0 之后，用真实的 `core/community.py` schema 校对一遍 `exCSV` 的 13 列与 community 表列名，预计只有字段名级别的微调。

## 四、验证方式（与仓库现有流程对齐）

原型通过了与你们 CI 同思路的检查：`node --check` 校验提取出的 `<script>`（语法零错误）；自动 i18n 覆盖检查（129 个 `t()` 键全部有中文，脚本同时解析主字典与 `Object.assign` 扩展块，可直接改造成 pytest 加入 `test_i18n_coverage`）；HTMLParser 标签配平检查；以及 grep 确认无 localStorage/无外部 URL。移植后建议把这三个检查（JS 语法、i18n 覆盖、无外部依赖）固化进测试套件，与 `test_no_vendor_imports.py` 并列——前端的"纯净性"和控制面的纯净性同样值得被 CI 守护。

---

## 五、v2 增补：硬件分析与 A/B 对比

原型在首版基础上新增两页（导航"基准"组内），全部数据接口假设与 `infermesh-milestone-2-prompt.md` 中 Commit 8 的 API 一一对应：

**硬件分析（Hardware Analysis）**，四个 tab：**效率**——每芯片 MBU（decode 带宽利用率）/ MFU（prefill 算力利用率）/ tok/J 读数卡、Roofline 图（实线为当前芯片屋顶、虚线为参照，圆点=各量化档 decode、方块=prefill，悬停出利用率）、跨芯片效率对比表（含 5 分钟持续负载 vs 突发的降频列）、四段式显存分解条（权重/KV/激活/碎片——GX-1 的 1.1GB 碎片就是靠这张图暴露的）；**容量**——吞吐–延迟前沿曲线（并发 1→64，SLO 档位 1/2/5/10s 可切，圆环=goodput 点）+ goodput 表（S60 在 2k 上下文下无法满足 ≤5s TTFT 属于 prefill 物理下限，空态文案已写明）；**扩展**——多卡张量并行加速比图（理想线性虚线 + 每点效率标签，GX-1 4→8 卡 81%→64% 的坍塌 vs A100/NVLink 的 82% 即互联问题的直接证据）；**分布**——p50/p90/p99/p99.9 分位表 + CV、ITL 直方图、尾部比与尖峰占比读数。

**A/B 对比（Compare）**：两侧各选芯片 + 驱动/SDK 版本，九项指标（tg/pp/TTFT p50/p99/ITL p99/峰值显存/功耗/tok-J/贪心一致率）并排 + Δ% 着色（|Δ|>2% 才判级，绿=改善红=回归）、驱动时间线图（红点自动标注相邻版本回归，S60 的 efsmi 2.5.120→2.5.136 有一个 -2.4% 示例）、数值正确性表（全芯片×量化的贪心一致率 / logit KL / PASS-WARN 徽章，4bit 档的 WARN 是刻意留的真实故事）。

**移植要点**：新增的五个 SVG 构建函数（`rooflineSVG / frontierSVG / scalingSVG / timelineSVG / histSVG`）与 `bindTTs` 通用 tooltip 均为纯函数、无相互依赖，随 `P.analysis / P.compare` 整体拷走即可；对数坐标助手 `lgX` 一并带上。MBU/MFU 的分母来自 `SPECS` 常量——真实版本换成芯片规格注册表 API（Milestone 2 Commit 2），公式已在 `core/derive.py` 的规格里锁定为与本原型一致。i18n 新增约 60 键位于文件末尾的 `Object.assign(ZH,{...})` 块，可整块搬运。
