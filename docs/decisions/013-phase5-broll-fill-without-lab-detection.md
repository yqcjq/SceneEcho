# 013. 跨 Phase 3/4 提前实施 Phase 5 的 B-roll 生成最小子集，不在 Lab 加用户素材诊断子能力

**日期**:2026-06-10
**状态**:已决策
**关联 Issue**:ISS-028

## 背景

Phase 2.6 完工后，PLAN.md 阶段总览（51-66 行）依赖链 `0 → 0.5 → 1A → 1B → 2 → 2.5 → 2.6 → 3 → 7 → 4 → 5` 推荐下一步是 Phase 3（长视频分步审核）。但 PLAN 2125 行 Phase 5 实际硬前置只列 1B / 2 / 2.5——3 / 7 / 4 是 demo 节奏推荐而非物理依赖。

口播视频补救画面单调度的能力基础设施已分散预埋在多处：

- `backend/app/extract/b_roll.py` 已识别样例每个 scene 的画面构成（`人物主导 / 全屏 B-roll / 画中画 / 侧栏`），写入 `Phase1AReport.b_roll_segments`，并已注册为 `api/lab.py` REGISTRY 中的 `b_roll` 子能力（ISS-023）。
- `backend/app/extract/skeleton.py::_infer_material_req` 已在 Slot 含非「人物主导」b_roll 段时优先标 `material_req="AI生成画面"`（决策优先级最高，覆盖 captions/stickers/zoom/mask 信号）。
- `backend/app/ir/project.py::ProjectIR.allow_aigc_broll: bool = False` + `PlacedSegment.use_aigc_broll: bool = False` + `PlacedSegment.aigc_broll_path: str | None` 三个字段都已存在。
- `backend/app/apply/fill.py:250-260` 的 `fill_gaps` 函数签名已含 `allow_aigc_broll` 形参，但函数体内显式 `log.info("fill.aigc_broll_requested_but_phase2_ignores")` 短路（PLAN 1587 锁 Phase 2 不引入 AIGC）。
- `backend/app/agent/aigc.py` 是 11 行的占位 re-export，`generate_broll` / `generate_sticker_image` 转发到 agent 包内的占位实现，没有任何真实第三方 API 接入。

ISS-027 ASR 修复后用户试用本地闭环，提出在 Phase 3/4 完成前先把 B-roll 视觉补充能力接通。最初提案（方案 A）希望在 SubcapabilityLab 加一个新子能力做"用户素材单调度检测"+ 集成到 SampleExtract / Editor。本决策评估该提案与三个替代方案，按"第一追求架构最优"原则重新划定本期范围。

## 被否定的方案

### 方案 A:在 SubcapabilityLab 新增"用户素材单调度检测"子能力 + 集成到 SampleExtract + Editor

最初提案。新建 `extract/b_roll_demand.py`（或 `apply/b_roll_demand.py`），对**用户素材**做画面单调度检测，输出"建议补 B-roll 的时间区间 + prompt 草稿"；在 `api/lab.py` REGISTRY 加新条目；前端 SampleExtract 显示样例的 b_roll 检测结果，Editor 显示用户素材的"单调时刻"建议。

否定原因:**作用域错位 + 重复实现既有能力 + 污染 Phase 1A 语义边界**，三个客观问题叠加。

1. SubcapabilityLab 当前定位是 "Phase 1A **样例**视觉理解能力的单点验证"——`Phase1AContext` 抽象（`extract/context.py`）的输入恒为 `(sample_id, normalized_path, task_id)`，11 个子能力（含 b_roll）都对样例视频运行。若加入"用户素材诊断"子能力，需要为 Lab 引入第二种 Context（ProjectContext），UI dropdown 也需要分叉成"样例检测 / 用户素材诊断"两类，破坏 Lab 既有的"任意子能力 × 任意样例自由组合"语义（ISS-024 刚收口）。
2. 用户描述的"识别需要补 B-roll 的时刻"在样例端**已经由 b_roll 子能力完成**——它把每个 scene 分类后写到 `Phase1AReport.b_roll_segments`，1B `skeleton._infer_material_req` 据此把对应 Slot.material_req 标 `AI生成画面`，apply 阶段消费该标签即可。Lab 里的 b_roll 条目现在就能跑（ISS-023 落地后），用户实际想要的"识别画面构成"功能已存在，再加一个会和它语义重叠。
3. 真有"对用户素材做主动单调度检测"诉求时，应放在 apply pipeline 内部（输出 `ProjectIR.aigc_broll_suggestions` 这类应用层 IR + `5.aigc.broll_plan` stage），而非 Phase 1A 的"样例理解"作用域。Phase1AReport 与 ProjectIR 的语义边界正是 ISS-007 二次核查时建立的（D17）——把"对用户素材的诊断"塞进 Phase1AReport / Lab 会让这条边界倒退。

### 方案 B:严格按 PLAN 依赖链顺序，先做完 Phase 3 / 4 / 7 再做 Phase 5

按阶段总览的推荐顺序串行推进。

否定原因:**PLAN 2125 行 Phase 5 硬前置只列 1B / 2 / 2.5**——本项目对依赖链已经做过显式拆分:"硬前置"（不满足则编译/运行级失败）vs"推荐顺序"（demo 节奏）。Phase 3（长视频 9-step pipeline + 条件审核 + Quality scoring，PLAN 1873-2055）/ Phase 4（标题条 + SFX 注入，PLAN 2057-2117）/ Phase 7（重排，PLAN 2157-2271）的能力与 Phase 5（生图 / 生视频）在数据流与 IR 写入路径上正交——前者扩展 PipelineState + 新增 review 组件 + 新 IR 模型，后者增 AIGC provider + apply/fill 钩子 + Editor 开关。串行推进会让 demo 在"短素材闭环已通 + B-roll 生成空缺"的状态停留 1-2 周，可解释性证据少一类（视觉补救能力）。

### 方案 C:完整实施 Phase 5（贴纸生图 + B-roll 生视频 + 封面生成 + 多 provider 选型）

按 PLAN 2119-2154 行 Phase 5 完整范围一次性落地，含 PLAN 2150 行待讨论项（视频生成 API 选型、时长上限处理、版权策略、cooldown / 余额警告）。

否定原因:**本期跨级动机收窄到"打通 B-roll 视觉补充能力"，封面与多 provider 选型是高成本独立子项**。

- PLAN 2150 行明确列封面 + 视频生成 API 选型为"待讨论"——评估 Runway / Sora / Kling / 即梦 / SD-Video 五条候选路径每条都需要独立调研（成本 / 时长上限 / 风格控制 / 中文 prompt 友好度 / 版权条款），单独可能耗时数日。
- 用户在本次诉求中明确"封面暂时还不需要"，需求自身已收窄。
- 一次性完成完整 Phase 5 会让本期改动跨多个独立功能（封面 LLM 文案 + 选图 UI + 视频生成 + 贴纸生图），后续二核成本陡增，违反 ISS-007 / ISS-010 / ISS-013 / ISS-018 等已积累的"小步迭代 + 二核还债"工作范式。

### 方案 D:按"用户素材主动诊断 → 自动生成"做闭环，Editor 不勾选

把方案 A 的"诊断"放到 apply pipeline 内（一个新 `5.aigc.broll_plan` stage），自动决定哪些 slot 启用 AIGC，跳过用户勾选；既不污染 Lab，又不依赖用户主动操作。

否定原因:**直接违反 D10「AIGC 用户主动触发」**（PLAN.md 90 行 + 关键设计决策章节明确列出）。D10 是项目层硬约束:AI 生图 / 生视频绝不自动启用，用户通过项目级开关或段级勾选明确授权，且产物上披露 AI 内容。"自动决定哪些 slot 启用 AIGC"无论包装得多好都跨过这条线，因此整体不可行。

## 最终决策

跨 Phase 3/4 直接进入 Phase 5 的**最小可用子集**——仅做 B-roll 视觉补充闭环，按以下边界划分。

**本期范围**（写代码,见 ISS-028 实施清单）:

1. `backend/app/agent/aigc.py` 升级为真实 provider 抽象:
   - `generate_broll(prompt: str, duration_sec: float, style_hint: dict, project_id: str) -> tuple[str | None, list[VisionEvent]]`:接入第三方视频生成 API（具体 provider 由 `.env` `AIGC_BROLL_PROVIDER` 配置，初期实现 1 个），按 `(prompt, style_hint, duration_sec)` 元组的 hash 缓存到 `data/aigc/broll/{hash}.mp4`。缺凭据 / API 错误 / 超时 → 返回 `(None, [warning_event])` 让上层 fallback。
   - `generate_sticker_image(description: str, style_hint: dict, project_id: str) -> tuple[str | None, list[VisionEvent]]`:贴纸生图，按 description hash 缓存到 `data/aigc/stickers/{hash}.png`。比 B-roll 轻、用户感知更快、是 demo 价值倍增的副产物。
   - 两个函数必发 `5.aigc.broll` / `5.aigc.sticker` stage VisionEvent（D13 强约束）+ 含 prompt 摘要 + 缓存命中 true/false + 实际耗时。

2. `backend/app/apply/fill.py` 新增 `_fill_aigc_broll` 策略分支:
   - 触发条件:`Slot.material_req == "AI生成画面"` 且 `ProjectIR.allow_aigc_broll == true`。
   - 行为:从 Slot 内 ASR 上下文（前后 ±2 个 Unit 的 text）+ 模板 tags + slot 持续时长合成 prompt → 调 `generate_broll(prompt, slot.duration.nominal, style_hint, project_id)` → 写 `PlacedSegment.aigc_broll_path` + `use_aigc_broll = True`。
   - 失败降级:provider 返 None 或异常 → fallback 到现有 `reuse` 策略 + 在 `ProjectIR.degraded["sections.0.segments.<i>.aigc_broll"]` 留 warning，不阻塞 pipeline。
   - 沿用 ISS-013 已建立的 `style_for_segment(slot, output_span)` 单一真理源算 timeline 位置。

3. `backend/app/api/projects.py::apply_short_endpoint` body schema 增 `allow_aigc_broll: bool = False`，直接落到 `ProjectIR.allow_aigc_broll`。

4. `backend/app/config.py::Settings` 增 `aigc_broll_provider: str = ""` / `aigc_broll_api_key: str | None = None` / `aigc_broll_max_duration_sec: float = 6.0`（保护性上限,主流 API 普遍 ≤ 6s）。

5. `frontend/src/pages/Editor.tsx` 在第三步 apply 卡片内增"允许 AI 补画面"checkbox（默认关，写 `ProjectIR.allow_aigc_broll`）+ 一行说明文字 "勾选后，含「AI生成画面」标签的 slot 会调用第三方视频生成 API。仅个人 demo 使用，请遵守生成内容审查与版权义务。"——D10 用户主动触发 + 显式风险披露。

6. `renderer/src/compositions/Project.tsx` 渲染 PlacedSegment 时优先 `aigc_broll_path`（视频源切到 AIGC 资源），缺路径回落到 user material；该字段已在 IR 预留位但未被消费。

7. `frontend/src/components/RemotionPlayer.tsx` 同步——`aigc_broll_path` 不空时 CSS 预览侧 `<video src>` 切到 AIGC 资源，与 renderer 视觉对齐（D30）。

**Lab 不动**——`b_roll` 子能力已在 REGISTRY，能跑、能在工作台看 b_roll_segments 字段填充，需求已满足。

## 已知代价

### 代价 1:短素材场景 B-roll 演示价值有限

PLAN 1582 行 Phase 2 ★MVP 闭环锁定 10–20s 一镜到底口播。这种素材本身画面单调度低（用户讲一段话，画面就是脸 + 字幕），样例如果全是「人物主导」Slot，apply 时不会触发 AI 生 B-roll。用户实际看到 B-roll 生成效果需要满足两条:(a) 样例视频本身含非「人物主导」段（让 b_roll 子能力分类出 `全屏 B-roll / 画中画 / 侧栏`，skeleton 标 `AI生成画面`）;(b) 短素材 + 该样例 apply 后某 Slot 命中 `AI生成画面`。

**Followup**:暂不追踪。fixture 准备是 Phase 5 实施时的运维事项（录 1-2 条样例视频含 B-roll 段即可），非架构问题，没必要开追踪条目。

### 代价 2:视频生成 API 延迟与成本不可预测

单条 B-roll 视频生成 API 调用通常 30s-3min，单价 $0.1-1.0;apply 阶段一段视频可能含多个 `AI生成画面` slot，最坏情况 apply 总时延翻 5-10 倍 + 成本不可控。本期不实施 cooldown / 余额警告 / 多 provider failover——按 hash 强制缓存（同 prompt / style 不重复支付）+ UI 显示 "AI 补画面" 的独立 loading state + apply 返回时附 `aigc_cost_summary` 字段（缓存命中数 / 实调次数 / 累计耗时）让用户看到代价。

**Followup**:future-plans/006-aigc-broll-provider-selection.md（多 provider 选型时一并讨论 cooldown / 余额警告）。

### 代价 3:跨 Phase 3 / 4 后回头补，可能产生设计冲突

Phase 3 的 9-step pipeline 在 Step 07（apply）会消费 `allow_aigc_broll`；Phase 4 的标题条 / SFX 注入与 apply/fill 流程并列。本期把 apply/fill 的 `aigc_broll` 策略实现完，Phase 3/4 接入时如果发现 long_pipeline 需要不同的 AIGC 触发时机（例如 Step 05 选模板时就要预估 AI 成本，影响选模板优先级），可能需要重构 fill.py 已有的策略分支。

**Followup**:ISS-029（占位 issue [暂缓]，Phase 5 B-roll 完成后启动 Phase 3 时一并审视）。

### 代价 4:D10 段级勾选退化为项目级勾选

PLAN 2143 行原文档描述 D10 时含"段级勾选"——用户对每个 PlacedSegment 单独决定是否生成 AI 补画面。本期 `allow_aigc_broll` 是项目级 boolean——用户勾一次即对所有 `AI生成画面` slot 启用，缺乏对单个 slot 的精细控制。理由:UI 复杂度 vs 本期 demo 价值的权衡——段级控制需要 PlacedSegment 列表交互 + 每段的预估成本预览 + 单段重生成按钮，工作量约等于本期所有其他改动之和。

**Followup**:ISS-030（占位 issue [暂缓]，待项目级勾选实际试用一段时间后决定是否升级到段级）。

### 代价 5:`generate_sticker_image` 接入但不直接被消费

本期范围实现 `generate_sticker_image` 是因为它和 `generate_broll` 共享 provider 抽象层（同一第三方账户，同一 hash 缓存模式，同一事件发射协议），一次性落地 marginal cost 极小。但 Phase 2 apply/style.py 当前对 `StickerEvent.generated_image` 缺失时已有占位渲染（`renderer/src/compositions/Sticker.tsx`），不会自动触发生图——本期同样不动那条调用链，sticker 的 AI 生成入口要等 TemplateLibrary 详情页加"为该模板生成所有贴纸"按钮（PLAN 2143 表第一行）才打通。

**Followup**:暂不追踪。函数实现 ready 后真要触发只是加一个 button + 一个端点，价值低于本期范围内的其他工作。

### 代价 6:第三方 API 内容审查与 prompt 注入防御不在本期范围

PLAN 2131 行明确"prompt 注入防御 + 内容审查（API 自带或调 moderation endpoint）"是 Phase 5 设计约束。本期只做 prompt 来源端的清洗（从 Slot 内 ASR text 抽取，本就是用户自己说的话，注入空间有限）+ 显式 UI 风险披露。完整 moderation endpoint 接入推迟。

**Followup**:暂不追踪。生成 prompt 全部来自用户自己的 Unit.text + 模板 tags（系统已审过的内容），没有外部用户输入通道，注入面非常窄;真要风险升级可在选 provider 时优先选自带 content moderation 的 API。

## 不在本期范围

### 不做 1:在 SubcapabilityLab 新增"用户素材单调度检测"子能力

样例端识别已由 Phase 1A b_roll 完成；用户端走 Editor 勾选 + apply 自动消费即可。

**Followup**:暂不追踪。如果未来真有"自动建议哪些 slot 启用 AIGC"诉求，应在 apply pipeline 内做 `5.aigc.broll_plan` stage，独立 issue 时再开;Lab 不该承担应用层诊断职能。

### 不做 2:封面生成（generate_cover）

用户当前需求明确不要;PLAN 2139 行原方案需 LLM 文案候选 + 用户选 + 生图 API 二者协同，独立工作量。

**Followup**:future-plans/005-aigc-cover-generation.md（新增占位文件，待 demo 阶段确认需求后启动）。

### 不做 3:视频生成 API 多 provider 选型评估

本期 `AIGC_BROLL_PROVIDER` 只接入 1 个具体 provider;多 provider 抽象 + 选型评估 + cooldown / 余额警告推迟。

**Followup**:future-plans/006-aigc-broll-provider-selection.md（新增占位文件）。

### 不做 4:Phase 3（长视频分步审核）/ Phase 4（标题条 + SFX）

仍按 PLAN 既定阶段顺序在 Phase 5 B-roll 子集完成后回头补;本期跨级仅是"前置部分 Phase 5"，不是"砍掉 Phase 3 / 4"。

**Followup**:ISS-029（占位 issue [暂缓]）。

### 不做 5:段级 AIGC 控制（per-PlacedSegment 勾选 + 单段重生成）

D10 原描述含段级勾选，本期退化为项目级 boolean。

**Followup**:ISS-030（占位 issue [暂缓]）。

### 不做 6:ARCHITECTURE.md / STRUCTURE.md 同步更新

按 000README.md 规范"只写当前事实"——决策仅声明意图，未实施代码前 `001ARCHITECTURE.md` 与 `002STRUCTURE.md` 的内容无变更（agent/aigc.py 仍是占位 / apply/fill.py 仍 ignore allow_aigc_broll）。ISS-028 实施完成后再按工作流补 ARCHITECTURE 链路 + STRUCTURE 文件描述。

**Followup**:ISS-028 实施完成时同步。
