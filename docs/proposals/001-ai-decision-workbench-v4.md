# 001 · AI 决策工作台 v4：从"AI 观测"到"AI 治理基础设施"

**日期**：2026-06-07
**状态**：📋 待决策（用户审阅中）
**关联**：PLAN.md v3.1 修订 / 核查报告 O1-O10

---

## 1. 背景与定位

v3.1 修订把"VLM 透明工作台"的边界拓宽到"AI 整体决策工作台"——D13 已约束所有 AI 调用（VLM/CV/ASR/audio/text_llm）必发 `VisionEvent`，事件总线 + SSE 链路 + 三栏 Workbench 页面已具雏形。

本提案讨论**在已有架构基础上的下一层第一性原理拔高**：当工作台已经成为所有 AI 决策的中央枢纽时，它能从"被动观测"升级为"AI 治理基础设施"，进而：

1. 成为答辩 demo 的核心产品力（不只是辅助页面）
2. 成为回归测试的金标准（events.jsonl 作 regression fixture）
3. 成为对外 API 的可解释性证据（评审/导师/外部系统的可观测出口）
4. 成为前端可视化的"决策图谱"（不只是事件列表，而是因果连线的甘特图/思考链）

**本提案的边界**：不修改 PLAN.md。每条提案给"现状 / 第一性原理 / 具体改动 / 代价 / 实施步骤"五段，等用户逐条拍板后再决定哪些进入 PLAN.md v3.2 或后续版本。

**优先级标识**：
- 🟢 **P1**：直接提升答辩 demo 价值密度，强烈建议进 v3.2
- 🟡 **P2**：架构合理性强但 demo 价值次要，可推到 Phase 实施期间决策

---

## 2. O11 · 多设备甘特图视图（用户强推 · 借鉴 TapFlow）🟢 P1

### 现状
v3 工作台只有"事件列表"形态（中栏倒序滚动卡片）。1A 各子能力并发跑、Phase 3 长视频 9 个 step 串行 + 内部并发，事件流时间维度的"谁先谁后、谁在跑谁等谁"这层信息**完全没视觉化**。新工程师 / 评审看中栏 60+ 条事件，不知道哪些是并行的、哪些是有依赖的、总耗时 30 分钟里时间花在哪。

### 第一性原理
**并发 AI 决策的本质是"任务图"而不是"任务列表"**。TapFlow 在 admin 后台已经验证过这套设计：用 D3.js 画"多设备调度甘特图"，每条横条 = 一次 attempt，竖线 = 决策时刻；同物理设备 lane 内自然 FIFO 串行，不同设备 lane 天然并行（`TapFlow-server/app/admin/templates/agent_detail.html` § Section 4）。SceneEcho 的"AI 决策时间线"在结构上与之同构：

- TapFlow 的 "device lane" ↔ SceneEcho 的 "stage lane"（每个 stage 一条 lane）
- TapFlow 的 "attempt 横条" ↔ SceneEcho 的 "VisionEvent 区间"（start_ts ~ end_ts）
- TapFlow 的 "decision tick 竖线" ↔ SceneEcho 的 "决策事件点"（瞬时事件，如"判定 CTA 字幕"）
- TapFlow 的 "device_locks 互斥" ↔ SceneEcho 的 "stage 依赖 DAG"（如 captions_anim 必须 await captions）

### 具体改动方案
新增工作台第四种视图（已有：列表 / 帧 / IR 树；新增：甘特图）。具体如下：

**前端**：
- `frontend/src/pages/WorkbenchGantt.tsx` 新增页面 / 或作为 `Workbench.tsx` 的可切换 tab
- 路由 `/workbench/:taskId?view=gantt`
- 用 D3.js v7（参考 TapFlow 的 CDN 引入即可，体积可控）画 SVG 甘特图：
  - **X 轴**：时间（秒，0 → 任务结束）
  - **Y 轴**：lane（每个 stage 一条 lane，按 stage 命名规范分组：1A.captions / 1A.stickers / 1A.zoom_direction / ... / 3.step02.vad / ...）
  - **横条**：每个 VisionEvent 的 `[start_ts, end_ts]` 区间；按 stage 染色（沿用 token）
  - **竖线**：瞬时决策事件（如 "判定 CTA"），高度跨整个 lane，hover 显示 reasoning
  - **连线**：`parent_event_id` 链上的事件间画 dashed line（参考 O3 因果链）
  - **lane 折叠**：默认只展开当前活跃的 stage，其他折叠
  - **点击事件**：点横条/竖线 → 联动跳到三栏页面对应事件
- 实现细节参考 `TapFlow-server/app/admin/templates/agent_detail.html` 第 230-296 行的 `window.AGENT_DATA` data island 模式 + D3 lane 渲染逻辑（可直接 fork 该代码骨架适配 SceneEcho 数据）

**后端**：
- `event_bus` 已有的 events 流足够支撑甘特图，无需新数据——但每个事件需要 `start_ts` 和 `end_ts`（或 `duration_ms`）。当前 VisionEvent 只有 `timestamp`，需要加 `duration_ms: int | None`（长程任务如 VLM 调用是区间，瞬时事件如"切点检测"为 0）
- `chat_vision()` 客户端层在返回 events 时自动填 `duration_ms = (end_time - start_time) * 1000`
- `GET /api/tasks/{id}/gantt` 端点：从 `events_{task_id}.jsonl` 聚合后给前端 D3 友好的格式（按 stage 分组的 lane 列表 + 全部 event 区间）

### 代价
- 前端工程量：2-3 天（D3 学习曲线 + lane 折叠 + 联动逻辑）
- VisionEvent 加 `duration_ms` 字段：影响 IR schema（需要重跑 gen-types + alembic migration / SQLite ALTER）
- 长视频任务事件多（500+）时 D3 渲染性能：需要 viewport-based virtualization（D3 自带 `d3-zoom` 可解决）

### 实施步骤
1. PLAN.md 加 VisionEvent.duration_ms 字段
2. Phase 0.5 后端改动追加 `GET /api/tasks/{id}/gantt` 端点
3. Phase 0.5 前端改动追加 `WorkbenchGantt.tsx` + D3 依赖
4. Phase 0.5 验证方式追加"甘特图渲染端到端"用例（mock 流跑通 → 甘特图显示 5+ lane + 10+ 横条）

### 与 TapFlow 的差异 / 创新点
- TapFlow 是"设备协同"（每条 lane = 物理设备）
- SceneEcho 是"AI 能力协同"（每条 lane = AI 子能力）—— **这在视频理解领域是首创可视化**，可作答辩亮点
- 评审打开甘特图能直接看到"30 秒任务里 VLM 字幕调用花了 5s、贴纸 8s、调色 3s 并发完成"这种总览，比逐条卡片更直观

---

## 3. O3 · 因果链可视化（parent_event_id 真正用起来）🟢 P1

### 现状
VisionEvent IR 已经有 `parent_event_id` 字段（PLAN.md 行 847），但 plan 没说哪些场景填、Workbench 如何渲染。当前事件流是"扁平时间序列"，看不出"这个事件因为前面那个事件才发生"。

### 第一性原理
**两阶段 VLM 调用是普遍模式**：贴纸语义判断依赖贴纸 bbox 检测、字幕功能分类依赖字幕样式识别、调色微调依赖 dominant_tag 判定。这些"思考链"是 AI 决策可解释性的金矿——评审看到"AI 先识别红色矩形 → 进而判为 CTA → 进而决定字幕样式 = 强调红色"这种连贯推理，远比单条事件更有说服力。

### 具体改动方案
1. **强约束**：所有两阶段（粗判 → 精化）的 VLM 调用，第二阶段事件必填 `parent_event_id` 指向第一阶段事件
2. **工作台中栏**：父子事件画 dashed line（父事件 → 子事件），hover 父事件高亮所有子事件，hover 子事件高亮父事件
3. **甘特图（O11）**：跨 lane 的因果链用细虚线连接，直观展示"字幕识别完成 → 字幕动画细节验证启动"的依赖
4. **新增 IR 字段**：VisionEvent 可加 `child_event_ids: list[str]`（双向链，便于工作台正反向遍历，避免 N 次扫全表找子节点）

### 代价
- 子能力实现时多写一行 `parent_event_id=prev_event.event_id`（一次性工作）
- 前端连线渲染（SVG path + 端点联动高亮）：1 天

### 实施步骤
1. PLAN.md "VLM 调用协议"加"两阶段调用 parent_event_id 强约束"小节
2. Phase 1A 各子能力实现细节里明确"凡是先粗判后精化的，第二阶段填 parent_event_id"
3. Workbench 中栏 + 甘特图渲染连线（与 O11 合并实现）

---

## 4. O2 · events.jsonl 反向用作 regression fixture 🟢 P1

### 现状
当前 events.jsonl 只用于回放观测（Phase 2.5 工作台事件回放页）。

### 第一性原理
**每个 events.jsonl 是一份完整的"AI 决策痕迹"**，等于一份天然的金标准 fixture。它能解决传统视频 ML 系统两个最痛的问题：
- **模型升级回归检测**：把 events.jsonl 重放进 mock VLM client → 验证新 VLM（如换 Qwen-VL → GPT-4o）行为差异；不需要真跑视频
- **集成正确性测试**：从 events 重建 IR，验证 IR round-trip 一致性（事件 → IR 是 pure function）

### 具体改动方案
1. **新增 fixtures 仓库目录** `tests/fixtures/golden_runs/{sample_id}_{task_id}/events.jsonl`：每个标杆样例 ingest 一次后，把对应 events.jsonl 复制进去 git-tracked
2. **新增 fixture mode**：`backend/app/llm/client.py` 加 `ReplayClient` 实现 `LLMClient` 接口，从 `golden_runs/` 读 events 重放出 `(structured_result, [])` —— 不调真实 API，但下游逻辑跑完整路径
3. **新增 CI job**：`pytest backend/tests/integration/test_golden_runs.py` 用 ReplayClient 跑全部 golden_runs → 验证最终 IR 与初次跑时一致（pydantic 对象深度比较）；任何 IR 字段语义变化（如改 placeholder_text 为 list[str]）都会立即被这个测试发现并强制更新 golden run
4. **新增 record mode**：`pytest --record-golden` 自动用真实 VLM 跑 + 把新 events 写回 golden_runs（人工 review 后 commit）

### 代价
- 第一次准备 golden_runs（~5 个标杆样例）需要真实 VLM 跑一次：~10 分钟 + 几十块 token 成本
- CI 跑 ReplayClient 是 pure function 测试，毫秒级，无额外成本

### 实施步骤
1. Phase 0.5 工作完成后立即建 `tests/fixtures/golden_runs/` 目录约定
2. Phase 1B 验证方式追加"用 ReplayClient 跑全部 golden_runs 验证 IR round-trip"用例
3. CI 流水线加 `golden-runs` job（不需 GPU，纯 CPU pytest）

---

## 5. O6 · 对外可解释性 API 🟡 P2

### 现状
events.jsonl 是文件形式，外部系统（评审 / 导师 / 第三方分析工具）拿不到结构化的决策溯源。OpenAPI spec 里只有 CRUD 接口，没有"为什么这个模板 / 项目长这样"的解释 API。

### 第一性原理
**可解释性应该是产品 API 的一等公民**，而不是藏在 jsonl 文件里。把"AI 决策痕迹"暴露成结构化 REST API 后，能：
- 评审直接 `curl /api/explainability/template/{id}` 拿到完整决策树
- 答辩 demo 直接展示"这个模板里 CTA 字幕的决策依据"（一个 API call）
- 未来接入分析工具（如 Notion / Obsidian / Anki）做 AI 教学素材

### 具体改动方案
1. **新增模块** `backend/app/api/explainability.py`：
   - `GET /api/explainability/sample/{id}` → `{ir: TemplateIR, decision_trace: list[VisionEvent], dependency_graph: list[ParentChildLink], summary_md: str}`
     - `summary_md` 是 Text LLM 把整个决策流总结成的可读 markdown（一段话 + 关键决策列表）
   - `GET /api/explainability/project/{id}` → 同上但针对 ProjectIR
   - `GET /api/explainability/template/{tid}/section/{sid}` 细粒度查询
2. **导出格式**：JSON / markdown / PDF 三选一（PDF 用 weasyprint）
3. **Workbench 加按钮**：「导出可解释性报告」一键拿 markdown 文件

### 代价
- 后端工程量：1-2 天
- LLM 生成 summary_md 每次调用成本：~$0.05（cacheable）

### 实施步骤
1. Phase 2.5 后端改动追加 `api/explainability.py`
2. 文档章节"AI 工具使用披露"指引评审用此 API 验证

---

## 6. O8 · SubcapabilityLab 提升一等公民 🟡 P2

### 现状
PLAN v3.1 把 SubcapabilityLab 标为 `dev only`（`import.meta.env.DEV` 守卫，生产 404）。

### 第一性原理
**1A 单点验证方法论是项目核心**（用户明确认可），它配套的工具不应该被藏起来。SubcapabilityLab 同时是：
- 开发者调试入口（不必跑全 extract 就能测某个 VLM 子能力）
- **评审快速验证子能力效果的入口**（"我想看 VLM 字幕识别准不准" → 直接进 lab 选 fixture + 子能力 → 跑 → 看工作台事件）
- 后期产品 telemetry 来源（生产中可让用户报告"这个子能力效果差"，自动跑 lab 收集证据）

### 具体改动方案
1. 删 `import.meta.env.DEV` 守卫，改为路由保留但**公开访问**
2. 重命名 `/lab` → `/diagnostics`（更产品化的命名）
3. 加 fixture 上传 UI：用户能上传自己的视频跑某个子能力测试
4. 加结果分享：跑完一个子能力后生成 sharable URL（含 task_id），别人能直接看回放
5. 加 baseline 历史曲线：每个子能力的指标随 commit 历史变化（CI 推数据进 SQLite）

### 代价
- 工程量：3-4 天（fixture 上传 + 历史曲线 chart）
- 生产环境暴露 lab 端点 → 需鉴权（与现有 auth 复用）

### 实施步骤
1. Phase 1A 完工后评估实际使用频率，决定是否升一等公民
2. 若决定升级：Phase 2 后增加 `/diagnostics` 产品化改造

---

## 7. O9 · VLM 成本 / 延迟仪表盘 🟡 P2

### 现状
当前事件有 `cost_tokens` 字段（VisionEvent IR），但散在事件里。答辩时评审可能问"总成本多少 / 哪个子能力最贵 / 平均延迟"——没有汇总仪表盘。

### 第一性原理
**任何 AI 系统都需要"看见自己烧了多少钱、慢在哪"**，否则优化无从下手。这也是答辩时"工程化成熟度"的硬指标。

### 具体改动方案
1. 新增 `backend/app/api/telemetry.py`：`GET /api/telemetry/cost?range=last_7d` → 按 stage 聚合 token 数 + USD 成本（参考 TapFlow 决策 023 的 `total_input_tokens/total_output_tokens/total_cost_usd` 三字段累加模式）
2. 新增前端 `/telemetry` 页面：饼图（按 stage 分布）+ 折线图（按日累计）+ Top 10 expensive tasks
3. tasks 表加 `total_cost_usd` 字段（参考 TapFlow `AgentSession.total_cost_usd`）
4. event_bus.publish() 时原子累加到 tasks 表

### 代价
- 工程量：2-3 天
- TapFlow 已有成熟模式可直接 fork

### 实施步骤
1. Phase 1B 后期引入（数据已有，UI 单独做）
2. CI 加"成本回归测试"：单 fixture extract 总 token 数 > 历史 +20% 时报警

---

## 8. O10 · 答辩演示动线 🟢 P1

### 现状
PLAN.md 描述了所有功能，但没说"答辩 30 分钟应该怎么演"。新人接手项目 → 上手 demo → 评审打分，三个角色对"演示路径"的期望完全不同。

### 第一性原理
**功能完成 ≠ 演示成功**。课题评分里 60% 是"展示效果"（评分项 6 迁移过程可视化 10 分 + 评分项 7 最终效果展示 10 分 + 加分项 10 分 + 完成度 7 分 ≈ 总分 40-50%）。没有演示动线规划，再好的功能也可能在评审面前哑火。

### 具体改动方案
在 PLAN.md 交付物章节后加一个新章节 "答辩演示动线"，按"开场 5 min → 工作台展示 8 min → NL 编辑 5 min → 长视频闭环 6 min → AIGC 加分 3 min → Q&A 备料 3 min" 拆解，每段：

1. **开场（5 min）**：项目愿景一句话 + 上传 sample_basic_15s → 立刻打开 `/workbench/{task_id}` → 演示 30+ 事件流（视觉冲击力最强）
2. **工作台深入（8 min）**：切到甘特图（O11）→ 展示并发能力 → 切回三栏 → 演示 VLM 因果链（O3）→ 演示否决事件 → 重跑该子能力
3. **NL 编辑（5 min）**：在 Editor 输入 3 条 NL → 工作台展示 LLM 解析 → Player 实时预览
4. **长视频闭环（6 min）**：上传 long_3min → Stepper UI 走完 9 step → 演示 Quality scoring 暂停 review
5. **AIGC 加分（3 min）**：演示封面生成（Phase 5）+ B-roll 占位
6. **Q&A 备料（3 min）**：备好 5 个高频问题（"成本多少 / 准确率多少 / 模型选型为什么 / 是否过拟合 / 如何应对 VLM 失败"）的工作台截图

附"答辩前 24h 检查清单"（fixtures 是否齐 / 工作台 SSE 是否稳 / 录屏 webm 是否能播 / API key 余额是否足）。

### 代价
- 文档工作量：半天
- 实际演示前需要 2-3 次彩排

### 实施步骤
1. 在 PLAN.md 交付物章节追加"答辩演示动线"小节（v3.2 候选）
2. Phase 全部完工后专门开 1 次"演示动线彩排"会

---

## 9. 总览：本提案 7 条优先级建议

| 编号 | 提案 | 优先级 | 工作量 | 答辩价值 | 建议进入 v3.2 |
|------|------|--------|--------|---------|--------------|
| O11 | 多设备甘特图视图（TapFlow 借鉴） | 🟢 P1 | 2-3 天 | ⭐⭐⭐⭐⭐ | ✅ 强烈 |
| O3 | 因果链 parent_event_id 可视化 | 🟢 P1 | 1 天 | ⭐⭐⭐⭐ | ✅ |
| O2 | events.jsonl 作 regression fixture | 🟢 P1 | 半天（约定）+ 持续维护 | ⭐⭐⭐（工程力） | ✅ |
| O10 | 答辩演示动线 | 🟢 P1 | 半天 | ⭐⭐⭐⭐（评分项） | ✅ |
| O6 | 对外可解释性 API | 🟡 P2 | 1-2 天 | ⭐⭐⭐ | 可选 |
| O8 | SubcapabilityLab 升一等公民 | 🟡 P2 | 3-4 天 | ⭐⭐ | Phase 后期再评 |
| O9 | VLM 成本 / 延迟仪表盘 | 🟡 P2 | 2-3 天 | ⭐⭐⭐（工程力） | 可选 |

**v3.2 建议范围**：把 4 条 P1 全部纳入（O11 + O3 + O2 + O10）。这 4 条的合并工作量约 5 天，全部围绕"工作台升级为答辩主舞台"这一主题，互相之间有协同（甘特图 + 因果链是同一套渲染管线 / events 作 fixture 必须有事件标准 / 演示动线必须有甘特图作开场冲击力）。

**v4 长远范围**：剩下 3 条 P2 + 未来更深的"AI 治理基础设施"演进（如 A/B 测试两个 VLM model、自动生成 prompt 改进建议、跨样例的"模板风格聚类"等）。

---

## 10. 与 PLAN.md 的关系

- 本提案**不修改 PLAN.md**。每条独立可决策。
- 用户拍板"O11 + O3 + O2 + O10 进 v3.2"后，我会做下一轮 PLAN.md 修订（追加新章节 + 调整 VisionEvent IR + Phase 0.5/1B/2.5 改动清单）。
- O8/O9 推迟到对应 Phase 启动时再评估，避免提前过度设计。
- O11 的甘特图视图是这一组最有"产品差异化"的亮点——参考 TapFlow 的 D3 实现可大幅降低工程风险（已有验证过的 SVG lane 渲染模式）。

---

## 11. TapFlow 甘特图实现关键参考

**文件**：`D:\Project\2026-3-TapFlow\TapFlow-server\app\admin\templates\agent_detail.html`

**核心模式**（O11 实施时可直接借鉴）：

1. **Data island**（230-244 行）：服务端直接把数据 inject 进 `window.AGENT_DATA = {...}` 全局对象，前端 JS 读这个对象渲染，避免额外 fetch
2. **D3 v7 CDN 引入**（230 行）：`<script src="https://d3js.org/d3.v7.min.js"></script>`
3. **SVG lane 渲染**（90-94 行 CSS 定义 `.lane-bg:nth-child(even)` 斑马纹 / `.gantt-bar` cursor pointer / `.decision-tick` 竖线样式）
4. **section 结构**（175-180 行）：`<section id="gantt-section">` → `<h2>多设备调度时间线 <span>每条横条 = 一次 attempt；竖线 = 决策时刻</span></h2>` → `<div id="gantt-chart" class="overflow-x-auto">`
5. **TOC 联动**（54 行）：右侧 sticky toc 用 `#gantt-section` 锚跳

**SceneEcho 适配清单**：
- TapFlow 的 `attempts_by_step` ↔ SceneEcho 的"按 stage 分组的 events"
- TapFlow 的 `decision_events` ↔ SceneEcho 的"瞬时 VisionEvent"
- TapFlow 的 device lane ↔ SceneEcho 的 stage lane
- TapFlow 用 8s 轮询活跃 session（admin 是后台静态视角）↔ SceneEcho 用 SSE 推送实时事件（工作台是实时视角）

**实施时建议**：开一个 `frontend/scripts/scaffold_gantt_from_tapflow.sh` 把 TapFlow agent_detail.html 的 D3 渲染逻辑 copy 出来作为起点，再适配 SceneEcho 的事件 schema。这能省下 60% 的"从零搭 D3 甘特图"的工程量。
