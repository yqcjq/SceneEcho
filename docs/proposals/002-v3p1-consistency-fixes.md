# 002 · v3.1 修订一致性修复指南（接手工程师执行清单）

**日期**：2026-06-07
**状态**：📋 待执行（21 处修订点，含 1 处 P0 阻塞 bug）
**关联**：PLAN.md v3.1 修订 / 001-ai-decision-workbench-v4.md
**预计工作量**：1-2 小时（如顺利无歧义）

---

## 0. 这份文档怎么用

本文档列出 v3.1 修订后通读核查发现的 **21 处** 内部不一致 / 描述过时 / 格式 bug。每条按以下结构组织：

1. **编号 + 优先级**：N1-N21 + 🔴 P0 / 🔴 P1 / 🟡 P2 / 🟢 P3
2. **位置锚定**：行号 + 上下文锚定字符串（行号会随修改漂移，**优先用锚定字符串定位**）
3. **当前文字**：精确复制 PLAN.md 中的现有内容
4. **建议新文字**：可直接复制粘贴的新内容
5. **依据**：为什么要改，引用哪条 D 约定 / 哪次改动 / 哪个交叉引用
6. **影响范围**：改动是否需要顺带改其他地方

**修复完成的判定标准**：底部"验收 grep 清单"全部返回预期结果。

**修改顺序建议**：按编号从 N1 改到 N21，但 N17（lab.py 错位）建议放最后做（结构性挪动，干扰行号定位）。

**关于"可保留"清单**：底部"附录 A · 看似不一致但实际合理的 6 处"列出**不要改**的位置，避免误改。

---

## 1. 根因总结（先理解为什么有这些 bug）

v3.1 修订时做了两个全局性改动，但没做"全文 grep 同步"，导致以下两类问题：

### 根因 1：D13 拓宽（V3 → v3.1）
v3 的 D13 只约束 VLM 调用（`chat_vision`），v3.1 拓宽到所有 AI 决策（VLM + Text LLM + ASR + audio + CV）。但修订时只改了 D13 本条 + v3.1 改动总结，**没遍历全文把"VLM 调用必发" 统改为 "AI 调用必发"**，导致 10+ 处描述停留在旧版（N4-N14）。

### 根因 2：events 路径方案 B 改动
v3.1 把事件文件路径从 `projects/{id}/pipeline/events.jsonl` 改为方案 B（`samples/{sid}/extracted/events_{task_id}.jsonl` / `projects/{pid}/pipeline/events_{task_id}.jsonl`）。但只改了 VisionEvent 生命周期段 + Phase 0.5 event_bus 章节，**关键机制章节的"事件持久化"和 Phase 3 D13 强化处的旧路径漏改**（N2、N3）。

### 单独的 schema 一致性 bug（N1）
v3.1 把 D13 拓宽时，扩展了 `VisionEvent.source` 枚举为 6 个值（vlm/cv/asr/audio/text_llm/system），**但 VisionEvent 数据结构定义本身（L937）只写了 5 个**——这是 schema 与规范的直接矛盾，会导致 Text LLM 调用发事件时 pydantic 校验 fail。

---

## 2. 修复清单

### 🔴 N1 · P0 · VisionEvent.source 缺 `text_llm`（schema bug）

**位置**：第 937 行，VisionEvent pydantic 模型定义内
**锚定上下文**：在 `class VisionEvent(BaseModel):` 块内的 source 字段

**当前文字**（精确）：
```python
    source: Literal["vlm", "cv", "asr", "audio", "system"]
```

**建议新文字**：
```python
    source: Literal["vlm", "cv", "asr", "audio", "text_llm", "system"]
```

**依据**：
- D13 全局约定（L104）明确说：`source ∈ {vlm, cv, asr, audio, text_llm, system}`
- v3.1 改动总结（L2121）明确说：`VisionEvent.source 枚举扩展为 {vlm, cv, asr, audio, text_llm, system}`
- 不修这条 → Phase 3 Step 03 LLM 去重的事件会 fail（`source="text_llm"` 不在 Literal 里 pydantic 报错）

**影响范围**：仅此一行。但下游 `gen-types` 跑完后 zod schema 也会自动同步，无需手动改前端类型。

---

### 🔴 N2 · P1 · 关键机制"事件持久化"段仍用旧路径

**位置**：第 598 行，"AI 透明工作台事件流"章节末尾
**锚定上下文**：紧接 L596 "用户在中栏可对任一事件'否决'..." 之后

**当前文字**：
```markdown
**事件持久化**：每个任务的事件流落 `projects/{id}/pipeline/events.jsonl`，Phase 2.5 的回放页面可按时间顺序重播全过程，作为答辩 demo 录屏的素材库。
```

**建议新文字**：
```markdown
**事件持久化**：每个任务的事件流按 v3.1 路径方案 B 落对应资源目录——`samples/{sid}/extracted/events_{task_id}.jsonl`（样例提取任务）或 `projects/{pid}/pipeline/events_{task_id}.jsonl`（项目应用任务），由 `event_bus.publish` 根据 `tasks.resource_kind + resource_id` 路由（详见"核心数据结构 · VisionEvent · 持久化路径"小节）。Phase 2.5 的回放页面可按时间顺序重播全过程，作为答辩 demo 录屏的素材库。
```

**依据**：
- v3.1 H1 修订（改动总结 L2125）：events 改方案 B
- VisionEvent 章节"持久化路径"小节（L954-958）已正确描述方案 B，此处与之矛盾

---

### 🔴 N3 · P1 · Phase 3 D13 强化又用了旧路径

**位置**：第 1758 行，Phase 3 "### 设计约束（本阶段必守）" 段最后一条
**锚定上下文**：以 `- **D13 v3 强化**：` 开头的行

**当前文字**：
```markdown
- **D13 v3 强化**：每个 step 的 LLM/VLM 调用使用专属 stage 前缀（`3.step02.vad` / `3.step03.dedup` / `3.step04.segment` / `3.step05.select` / `3.step08.quality`），事件流落 `pipeline/events.jsonl`；工作台支持按 stage 过滤，每个 step 的 review UI 加「打开工作台看本 step 决策过程」按钮直接深链跳转 `/workbench/{task_id}?stage_filter=3.step{n}`。Step rerun 时清除对应 stage 的历史事件，避免回放混乱。
```

**建议新文字**：
```markdown
- **D13 v3 强化**：每个 step 的 LLM/VLM/audio/CV 调用使用专属 stage 前缀（`3.step01.asr` / `3.step02.vad` / `3.step03.dedup` / `3.step04.segment` / `3.step05.select` / `3.step08.quality` / `3.step09.render`），事件流按方案 B 落 `projects/{pid}/pipeline/events_{task_id}.jsonl`；工作台支持按 stage 过滤，每个 step 的 review UI 加「打开工作台看本 step 决策过程」按钮直接深链跳转 `/workbench/{task_id}?stage_filter=3.step{n}`。Step rerun 时按 task_id 软关闭旧 events 文件 + 新建新文件（事件不残留、不混淆）。
```

**改动点**：
1. stage 列表补 `3.step01.asr` 和 `3.step09.render`（D13 拓宽后 ASR 也发事件、render 进度也走同通道）
2. `pipeline/events.jsonl` → `projects/{pid}/pipeline/events_{task_id}.jsonl`
3. rerun 处理改为方案 B 的"新建文件"机制

**依据**：v3.1 H1 路径方案 B + N15 stage 命名规范表覆盖（见 N19）

---

### 🔴 N4-N14 · P1 · D13 拓宽未同步的 10 处描述

这 10 处都是 v3.1 D13 拓宽（VLM 调用 → 所有 AI 决策）的遗漏修订。**逐处给精确改动**：

#### N4 · 视频理解技术选型表后段

**位置**：第 139 行
**当前文字**：
```markdown
**所有 VLM 调用必发射 VisionEvent**：见"关键机制·AI 透明工作台事件流"章节。这是 v3 引入的强约束——任何 `llm.client.chat_vision()` 不发事件视为 bug，CI 检查 grep。
```

**建议新文字**：
```markdown
**所有 AI 调用必发射 VisionEvent**（v3.1 D13 拓宽）：见"关键机制·AI 透明工作台事件流"章节。强约束——任何 `llm.client.chat_vision()` / `chat_text()` / ASR / VAD / Demucs 等 AI 客户端方法不发事件视为 bug，CI 通过 `scripts/check_event_emission.py` 扫源码强制校验。
```

---

#### N5 · "AI 透明工作台事件流"章节核心描述

**位置**：第 581 行，章节首句
**锚定上下文**：紧跟 `#### AI 透明工作台事件流（v3 新增 · 与账本机制并列的项目第二 novel 设计）` 标题

**当前文字**：
```markdown
**核心**：所有 VLM 调用同步发射结构化的 `VisionEvent`，通过 SSE 事件总线实时推送到前端 `/workbench/{task_id}` 三栏页面。VLM "看到什么 / 怎么想 / 决定了什么"三件事被结构化、可订阅、可回放、可否决。
```

**建议新文字**：
```markdown
**核心**：所有 AI 决策（v3.1 D13 拓宽：VLM 视觉、Text LLM 文本、ASR 转写、Demucs/librosa 音频、CV 信号处理）同步发射结构化的 `VisionEvent`，通过 SSE 事件总线实时推送到前端 `/workbench/{task_id}` 三栏页面。AI "看到/听到什么 / 怎么想 / 决定了什么"三件事被结构化、可订阅、可回放、可否决。
```

---

#### N6 · 标题 "VLM 调用协议"

**位置**：第 607 行
**当前文字**：
```markdown
#### VLM 调用协议（v3 强约束）
```

**建议新文字**：
```markdown
#### AI 调用协议（v3 强约束 · v3.1 拓宽到全部 AI 客户端）
```

**关联改动**：该章节内部的"契约"示例代码（L611-624）目前只展示 `chat_vision` 签名。建议在该代码块**之后**追加一段：

```markdown
**对其他 AI 客户端方法的同等约束（v3.1 拓宽）**：`chat_text()`、ASR 客户端、Demucs 等所有 AI 调用必采用相同模式——返回 `tuple[BaseModel, list[VisionEvent]]` 元组，内部调 `event_bus.publish()`，event.source 按调用类型填 `text_llm` / `asr` / `audio` 等。签名规范：
\`\`\`python
def chat_text(messages, model, stage, task_id, ir_target_template, schema) -> tuple[BaseModel, list[VisionEvent]]: ...
def transcribe(audio_path, stage, task_id, ir_target_template) -> tuple[TranscriptLedger, list[VisionEvent]]: ...
\`\`\`
```

---

#### N7 · VisionEvent 章节首句

**位置**：第 920 行
**锚定上下文**：紧跟 `### VisionEvent（v3 新增 · AI 透明工作台的核心 IR）` 标题

**当前文字**：
```markdown
每次 VLM 调用的"副产品"，由 `llm.client.chat_vision()` 强制返回，由 `event_bus` 广播到前端工作台。它把"VLM 看到什么 / 怎么想的 / 决定写入 IR 哪个字段"三件事结构化。
```

**建议新文字**：
```markdown
每次 AI 决策的"副产品"（v3.1 D13 拓宽，含 VLM/Text LLM/ASR/audio/CV），由 `llm.client.chat_vision()` / `chat_text()` / 各 AI 客户端方法强制返回，由 `event_bus` 广播到前端工作台。它把 AI "看到什么 / 怎么想的 / 决定写入 IR 哪个字段"三件事结构化。
```

---

#### N8 · model_used 字段注释

**位置**：第 938 行
**当前文字**：
```python
    model_used: str | None       # VLM 调用时填具体 model id，便于 cross-check 对比
```

**建议新文字**：
```python
    model_used: str | None       # AI 调用时填具体 model id（VLM/Text LLM 都填），便于 cross-check 对比；CV/audio 等非模型来源填 None
```

---

#### N9 · cost_tokens 字段注释

**位置**：第 949 行
**当前文字**：
```python
    cost_tokens: int | None      # VLM 调用 token 数，工作台可展示但不当作核心约束
```

**建议新文字**：
```python
    cost_tokens: int | None      # AI 调用 token 数（VLM/Text LLM 都填），工作台可展示但不当作核心约束；CV/audio 等非 token 来源填 None
```

---

#### N10 · Phase 0.5 设计约束 D13

**位置**：第 1230 行
**当前文字**：
```markdown
- D13：所有 VLM 调用必发射 VisionEvent（本阶段建立这条契约的客户端层）。
```

**建议新文字**：
```markdown
- D13（v3.1 拓宽版）：所有 AI 调用（VLM / Text LLM / ASR / audio / CV）必发射 VisionEvent；本阶段建立这条契约的客户端层（chat_vision + chat_text 两套签名均符合 v3 协议）。
```

---

#### N11 · Phase 0.5 强约定只规定了 chat_vision

**位置**：第 1254 行
**锚定上下文**：在 `- **新增** backend/app/llm/client.py（占位骨架，1A 才填真实逻辑）：` 下面

**当前文字**：
```markdown
  - **强约定**：`chat_vision` 签名必为 `(messages, model, stage, task_id, frames, ir_target_template, schema) -> tuple[BaseModel, list[VisionEvent]]`；本阶段实现内部直接构造 mock VisionEvent 列表、调 `event_bus.publish()`、返回 mock 结构化结果
```

**建议新文字**：
```markdown
  - **强约定（v3.1 拓宽）**：
    - `chat_vision` 签名必为 `(messages, model, stage, task_id, frames, ir_target_template, schema, silent=False) -> tuple[BaseModel, list[VisionEvent]]`
    - `chat_text` 签名必为 `(messages, model, stage, task_id, ir_target_template, schema, silent=False) -> tuple[BaseModel, list[VisionEvent]]`（无 frames 参数，其余同 chat_vision）
    - 本阶段两个方法的实现都内部直接构造 mock VisionEvent 列表、调 `event_bus.publish()`、返回 mock 结构化结果
    - 后续 Phase 3 的 dedup/segment 等 Text LLM 调用直接走 `chat_text`，自动满足 D13
```

---

#### N12 · Phase 1A 验证 5 grep 命令

**位置**：第 1447 行
**当前文字**：
```markdown
5. **D13 约束验证**：故意把 `chat_vision()` 内部的 `event_bus.publish` 注释掉 → CI grep `chat_vision.*publish` 检查脚本红。
```

**建议新文字**：
```markdown
5. **D13 约束验证**（v3.1 拓宽）：CI 脚本 `scripts/check_event_emission.py` 扫所有 AI 客户端方法（`chat_vision` / `chat_text` / ASR / VAD / Demucs 调用点）是否都在返回前调过 `event_bus.publish`；故意删任一处的 publish → CI 红。验证方式：人为把 `chat_text()` 内的 publish 注释掉 → 期望 CI 报告"chat_text at backend/app/llm/client.py:LXX missing event_bus.publish"。
```

---

#### N13 · 关键设计决策 D13 描述（这条是规则总览，不是历史快照）

**位置**：第 2381 行，"关键设计决策"列表内
**当前文字**：
```markdown
- **D13 VLM 调用必发射 VisionEvent（v3 新增）** —— AI 透明工作台的可观测性底座，CI 强制约束。
```

**建议新文字**：
```markdown
- **D13 所有 AI 调用必发射 VisionEvent（v3 新增 · v3.1 拓宽）** —— 不只 VLM，含 Text LLM / ASR / audio / CV 所有 AI 决策。AI 透明工作台的可观测性底座，CI 强制约束。
```

---

#### N14 · "已明确不做"里的 VLM 静默调用

**位置**：第 2370 行
**当前文字**：
```markdown
- **VLM 静默调用**（v3 新增）：所有 `chat_vision()` 必发射 VisionEvent；不发事件的 vision call 视为 bug，CI grep 强制。
```

**建议新文字**：
```markdown
- **AI 静默调用**（v3 新增 · v3.1 拓宽）：所有 AI 客户端方法（`chat_vision` / `chat_text` / ASR / Demucs 等）必发射 VisionEvent；不发事件的调用视为 bug，CI `scripts/check_event_emission.py` 强制扫源码。`silent=True` 模式仅用于背景 sanity check 等明确不需要在工作台展示的辅助调用（详见"VLM 调用协议·silent 模式"小节）。
```

---

### 🟡 N15 · P2 · v3 改动总结 Patch op 数量错（5→4）

**位置**：第 2179 行，"### v3" 改动总结的"核心数据结构变更"段第 4 条
**当前文字**：
```markdown
4. `Patch` 加 5 个 op：`set_placeholder_text` / `set_length_constraint` / `set_semantic_purpose` / `replay_vision_event` / `reject_vision_event`；加 `triggered_by_event_id` 与 `source="workbench"` 字段追溯。
```

**建议新文字**：
```markdown
4. `Patch` 加 4 个 op：`set_placeholder_text` / `set_length_constraint` / `set_semantic_purpose` / `reject_vision_event`；加 `triggered_by_event_id` 与 `source="workbench"` 字段追溯。（v3.1 修订：`replay_vision_event` 已从 Patch 移除，改为 Workbench API `POST /workbench/{task_id}/reject-event/{event_id}`——因为它本质是 UI 操作不修 IR，详见 v3.1 S6 修订）
```

**依据**：v3.1 改动总结（L2151）S6 明确说 `replay_vision_event` 已移除。Patch op 实际列表（L1106-1135）也只有 4 个 v3 新增 op（无 replay_vision_event）。本处描述与现状矛盾。

---

### 🟡 N16 · P2 · Phase 7 前置条件 Phase 3 验证数过时

**位置**：第 1983 行，Phase 7 前置条件第 1 条
**当前文字**：
```markdown
- Phase 3 长视频分步审核管线稳定（除 Step 06 之外的 8 个 step 均能跑通，Phase 3 6 项验证全过）。
```

**建议新文字**：
```markdown
- Phase 3 长视频分步审核管线稳定（除 Step 06 之外的 8 个 step 均能跑通，Phase 3 **7 项验证全过**——v3.1 加了第 7 项"工作台 per-step 验证"）。
```

**依据**：Phase 3 的"验证方式"段（L1847-1868）实际有 7 条验证，第 7 条是 v3.1 加的：
```
7. **v3 工作台 per-step 验证**：完成完整 9 step 跑通后访问 /workbench/{task_id}?stage_filter=3.step03 → 只看到 dedup 相关 VisionEvent ...
```

---

### 🟢 N17 · P3 · lab.py 错误归类到 Phase 1A "### 前端改动"段下

**位置**：第 1428-1432 行，Phase 1A 的 `### 前端改动` 标题正下方
**当前结构**：
```markdown
### 前端改动
- **新增** `backend/app/api/lab.py`（v3 新增 · H5）：仅 `ENABLE_DEV_MOCK=true` 时挂载
  - `GET /api/lab/subcaps` 返回所有可单点跑的子能力列表 `[{name, fixtures: [...], baseline_path}]`
  - `POST /api/lab/run-subcap/{name}` body `{fixture_id, dry_run?}` → 创建 task ...
  - `GET /api/lab/baselines/{name}` 返回 `tests/baselines.json/subcap.<name>` 当前基线数值
- **新增** `frontend/src/pages/SubcapabilityLab.tsx`（v3 关键页 · S11：...）：单点验证工作台
  ...
```

**问题**：`backend/app/api/lab.py` 是后端模块，却写在"前端改动"标题下，读 plan 时新工程师会困惑。

**建议修改**：在 Phase 1A 的"### 后端改动（按子能力分组，每组独立可交付）"段内，**找到"#### 字幕功能分类（VLM，沿用 v2.4）"子段末尾**，追加一个新子段：

```markdown
#### SubcapabilityLab 后端入口（v3 新增 · H5）
- **新增** `backend/app/api/lab.py`：仅 `ENABLE_DEV_MOCK=true` 时挂载
  - `GET /api/lab/subcaps` 返回所有可单点跑的子能力列表 `[{name, fixtures: [...], baseline_path}]`
  - `POST /api/lab/run-subcap/{name}` body `{fixture_id, dry_run?}` → 创建 task（resource_kind=sample, resource_id=fixture_id）→ BackgroundTask 调对应 `detect_X(...)` → 返回 `{task_id, workbench_url}`
  - `GET /api/lab/baselines/{name}` 返回 `tests/baselines.json/subcap.<name>` 当前基线数值
```

然后**从"### 前端改动"段开头删除整个 `- **新增** backend/app/api/lab.py（v3 新增 · H5）` 块**（包括其下 3 行 GET/POST/GET 缩进项），只保留 frontend 的 SubcapabilityLab.tsx 等条目。

---

### 🟢 N18 · P3 · fixtures 矩阵路径约定段紧接表格无空行

**位置**：第 1336-1338 行，Phase 1A "### Fixtures 矩阵" 段
**当前结构**：
```markdown
### Fixtures 矩阵（用户准备 / 一次性补齐）

**路径约定（v3 统一 · S12）**：开发期 fixtures 放 `tests/fixtures/{sample_id}/source.mp4`...（这一行结尾）
| Fixture | 用途 | 关键人工标注 |
| --- | --- | --- |
| `sample_basic_15s` | ... |
```

**问题**：路径约定段（一整段文字）和表格首行 `| Fixture | ...` 之间**没有空行**。markdown CommonMark 规范要求表格前必须有空行，否则表格被解析为段落延续，渲染时表格不出现。

**建议修改**：在 `**路径约定（v3 统一 · S12）**：...` 那段文字结尾（含句号）之后插入一行空行，然后才是 `| Fixture | 用途 | 关键人工标注 |`。

精确改动（在 L1336 行后插入一个空行）：

修改前：
```
...（不带前缀路径），实际加载时由 `tasks_store.get_sample_path(sample_id)` 路由到 `data/samples/{sid}/normalized.mp4`。
| Fixture | 用途 | 关键人工标注 |
```

修改后：
```
...（不带前缀路径），实际加载时由 `tasks_store.get_sample_path(sample_id)` 路由到 `data/samples/{sid}/normalized.mp4`。

| Fixture | 用途 | 关键人工标注 |
```

---

### 🟢 N19 · P3 · stage 命名规范表 Phase 3 缺 step01.asr / step09.render

**位置**：第 656 行，"#### stage 命名规范（v3 强约束 · H2）" 章节内的表格

**当前文字**：
```markdown
| `3.step{NN}.{kind}` | Phase 3 长视频 step | 橙 | `3.step02.vad` / `3.step03.dedup` / `3.step04.segment` / `3.step05.select` / `3.step06.reorder.score` / `3.step06.reorder.deps` / `3.step06.reorder.plan` / `3.step07.apply` / `3.step08.quality` |
```

**建议新文字**（补 `3.step01.asr` 和 `3.step09.render`，同时在示例集中前补 step01、末补 step09）：
```markdown
| `3.step{NN}.{kind}` | Phase 3 长视频 step | 橙 | `3.step01.asr`（ASR 转写，source="asr"）/ `3.step02.vad` / `3.step03.dedup` / `3.step04.segment` / `3.step05.select` / `3.step06.reorder.score` / `3.step06.reorder.deps` / `3.step06.reorder.plan` / `3.step07.apply` / `3.step08.quality` / `3.step09.render`（渲染进度，event 类型 progress 而非 vision）|
```

**依据**：
- D13 v3.1 拓宽后，Step 01 ASR 也是 AI 决策（source="asr"），应有事件
- Step 09 render 进度通过 SSE 通道发送（类型 `progress` 不是 `vision`），但也走 stage 体系，需登记
- 这与 N3 的 Phase 3 D13 强化里"`3.step01.asr` / `3.step09.render`"是一致的

---

### 🟢 N20 · P3 · CI 校验脚本名引用一致性

**追加要求**：N4 / N12 / N14 都引用了 `scripts/check_event_emission.py`（v3.1 提到 `scripts/check_stage_naming.py` 但没提 event_emission 脚本）。如果新工程师以为这是已存在脚本会找不到——它是**需要新写**的。

**建议**：在 `### 测试 / 可观测性 / CI 策略` 章节的"CI 流水线"yaml 块下方（第 901 行下面）追加一段：

```markdown
**v3.1 新增 CI 校验脚本**（在 Phase 0.5 实施时一并创建）：
- `scripts/check_stage_naming.py`：grep 源码所有 `stage="..."` 字面量，校验是否匹配"stage 命名规范"表的前缀模式；不匹配则 fail（参考 H2）
- `scripts/check_event_emission.py`（v3.1 新增）：grep 所有 AI 客户端方法定义（`def chat_vision` / `def chat_text` / `def transcribe` / `def extract_bgm` 等），校验函数体内是否调用了 `event_bus.publish`；缺则 fail（参考 D13 + N4/N12）
```

---

### 🟡 N21 · P2 · 几处文字误改（v3 改动总结里的 source 描述）

**位置**：第 2176 行
**当前文字**：
```markdown
1. 新增 `VisionEvent` + `IRTarget`：AI 工作台事件总线的核心 IR。`source ∈ {vlm, cv, asr, audio, system}`，含 `frame_url / bbox_norm / semantic_label / reasoning / confidence / ir_target / ir_value / cost_tokens` 等字段。生命周期 = 内存广播 + `projects/{id}/pipeline/events.jsonl` 持久化。
```

**问题**：这条在 v3 改动总结里，按"已写阶段的描述不修改"规则**通常不改**，但这里同时包含两条已被 v3.1 修订的事实（source 5 个、旧路径），读起来与现状矛盾。

**建议处理**：**不改原文**，但在该行**末尾追加一句**：
```markdown
（v3.1 修订：source 已扩展为 6 个含 `text_llm`；持久化路径已改方案 B，详见 v3.1 改动总结 H1）
```

修改后：
```markdown
1. 新增 `VisionEvent` + `IRTarget`：AI 工作台事件总线的核心 IR。`source ∈ {vlm, cv, asr, audio, system}`，含 `frame_url / bbox_norm / semantic_label / reasoning / confidence / ir_target / ir_value / cost_tokens` 等字段。生命周期 = 内存广播 + `projects/{id}/pipeline/events.jsonl` 持久化。**（v3.1 修订：source 已扩展为 6 个含 `text_llm`；持久化路径已改方案 B，详见 v3.1 改动总结 H1）**
```

**同理处理 L2180**：
```markdown
5. 全局约定加 `D13 VLM 调用必发射 VisionEvent`（CI grep 强制校验）。**（v3.1 拓宽：D13 已从 VLM 调用扩到所有 AI 调用，详见 v3.1 改动总结"架构层拔高"）**
```

---

## 3. 附录 A · 看似不一致但实际合理的 6 处（不要改）

执行核查时可能也会注意到下面 6 处也包含"VLM 调用"字样，但**它们是合理的，不要改**：

| 序号 | 位置 | 内容 | 为什么保留 |
|------|------|------|-----------|
| K1 | L585 | "如果让 VLM 的视觉理解输出'只返回结构化结果给后端处理'（v2.4 默认做法）" | 这是反例对比，特指 v2.4 当时的 VLM 路径，改成"AI"反而失真 |
| K2 | L641 | dual-model cross-check 启用规则里的"chat_vision" | dual-check 本身就是 VLM 视觉决策的特殊场景（双 provider 一致才写 IR），Text LLM 没这个需求 |
| K3 | L1355 | Phase 1A 客户端重构里"`chat_vision()`：实现 v3 协议..." | 是该方法的实现细节描述，本身就是说 vision 方法 |
| K4 | L778-798 | Agent 工具协议章节所有函数签名都没 task_id 参数 | 这些是工具的抽象 IO schema，task_id 是 runtime context 不属于工具 schema |
| K5 | L2176 / L2180 | v3 改动总结里的 source 5 个 / "VLM 调用必发" 描述 | 已通过 N21 在原文追加 v3.1 修订标注，保留 v3 历史描述 |
| K6 | L598 周围反例段（"如果让 VLM 的视觉理解输出只返回结构化结果"） | 同 K1 | 反例对比，特指 VLM 路径 |

---

## 4. 执行流程建议

### 步骤 1：先做 N1（schema bug 必修，不修代码跑不了）
1. 修改 `PLAN.md:937` 一行
2. 跑 `python scripts/gen_schema.py` 重生成 JSON Schema
3. 跑 `pnpm gen:types` 同步前端/renderer 类型

### 步骤 2：批量做 D13 拓宽（N4-N14）+ 路径方案 B（N2-N3）
建议用一个 Python 脚本批量替换（参考 v3.1 之前用的 `_patch_plan_*.py` 模式）。每个替换都用**完整的多行锚定**，避免字符串歧义。

### 步骤 3：单点做组织/格式（N15-N19）
- N15 v3 改动总结 Patch op 数量改 5→4
- N16 Phase 7 前置改 6→7
- N17 lab.py 挪到后端段（结构性挪动，单独做避免干扰其他改动）
- N18 fixtures 表格前补空行
- N19 stage 表补 step01.asr / step09.render

### 步骤 4：补 N20 CI 脚本约定
在"CI 流水线"yaml 块下追加 `scripts/check_event_emission.py` 等约定说明。

### 步骤 5：N21 v3 改动总结追加 v3.1 修订标注
不改原文，只在末尾追加括号说明。

---

## 5. 验收 grep 清单（修复完成后逐条跑，全部应返回预期结果）

```bash
# 验收 1：VisionEvent.source 必须含 text_llm（N1）
grep -n 'Literal\["vlm".*"system"\]' PLAN.md
# 期望：返回 0 行；若仍有 → N1 未修

# 验收 2：events.jsonl 单数路径（无 _{task_id}）必须只剩 v3 改动总结里 1 处（N2/N3）
grep -nE '/pipeline/events\.jsonl[^_]' PLAN.md
# 期望：返回 1 行，仅 L2176（v3 改动总结的历史描述，N21 已加标注）

# 验收 3：所有 VLM 调用必发射（N4-N14）应只剩 v3 改动总结里 2 处
grep -nE '所有 VLM 调用必发|VLM 调用必发射' PLAN.md
# 期望：返回 2 行，L2180 + L2381 应已被改为 "所有 AI 调用必发射"，若仍有其他行 → N4/N5/N10 未完成

# 验收 4：D13 拓宽后多处描述已统一
grep -nE 'VLM 调用 token 数|VLM 调用时填' PLAN.md
# 期望：返回 0 行（N8/N9 已修）

# 验收 5：Patch op 5 个 → 4 个（N15）
grep -nE 'Patch 加 5 个 op|加 5 个 op' PLAN.md
# 期望：返回 0 行

# 验收 6：Phase 7 前置 7 项验证（N16）
grep -nE 'Phase 3.*6 项验证' PLAN.md
# 期望：返回 0 行

# 验收 7：lab.py 应在后端段（N17）
python -c "
import io
with io.open('PLAN.md','r',encoding='utf-8') as f: lines=f.readlines()
in_phase1a, in_frontend = False, False
for i, line in enumerate(lines, 1):
    if line.startswith('## 阶段 1A'): in_phase1a = True
    elif line.startswith('## 阶段 1B'): in_phase1a = False
    if in_phase1a and line.strip() == '### 前端改动': in_frontend = True; continue
    if in_phase1a and in_frontend and line.startswith('### '): in_frontend = False; break
    if in_frontend and 'backend/app/api/lab.py' in line:
        print(f'FAIL L{i}: lab.py 仍在 1A 前端改动段')
print('OK' if not in_frontend or 'backend/app/api/lab.py' not in ''.join(lines[lines.index(l):lines.index(l)+20]) else '')
"
# 期望：无 FAIL 输出

# 验收 8：fixtures 表格前空行（N18）
python -c "
import io
with io.open('PLAN.md','r',encoding='utf-8') as f: lines=f.readlines()
for i, line in enumerate(lines, 1):
    if line.strip().startswith('| Fixture | 用途 |'):
        prev = lines[i-2].strip() if i >= 2 else ''
        if prev: print(f'FAIL L{i}: 表格前缺空行')
        else: print(f'OK L{i}: 表格前有空行')
"
# 期望：OK，不是 FAIL

# 验收 9：stage 表覆盖 step01/step09（N19）
grep -nE '3\.step01\.asr|3\.step09\.render' PLAN.md
# 期望：返回 ≥ 2 行（stage 表 + N3 Phase 3 D13 强化里也用了）

# 验收 10：CI 脚本约定（N20）
grep -nE 'check_event_emission|check_stage_naming' PLAN.md
# 期望：返回 ≥ 3 行（CI 章节 + N4/N12/N14 三处引用都对得上）

# 验收 11：v3 改动总结的 v3.1 修订标注（N21）
grep -nE '已扩展为 6 个含 \`text_llm\`|v3\.1 已从 VLM 调用扩到所有 AI 调用' PLAN.md
# 期望：返回 ≥ 2 行（L2176 / L2180 都有标注）
```

---

## 6. 关于这次修复的根因学习（给后续修订者的建议）

v3.1 出现这些遗漏修订的根因是**全局性改动没有配套 grep 校验**。建议未来任何涉及以下情况的改动，必跟一次 grep 全文同步：

1. **改 D 约定的范围**（如 D13 从 VLM 拓宽到所有 AI）→ grep 旧描述
2. **改文件路径约定**（如 events 路径方案 B）→ grep 旧路径
3. **改 IR 字段定义**（如 source 枚举扩展、placeholder_text 改 list）→ grep 字段引用
4. **删除 Patch op / 数据字段**（如 replay_vision_event 移除）→ grep 该名

提供一个简单的 PR 模板片段供未来用：

```markdown
## 改动是否包含全局性约定？
- [ ] 我改了某条 D 约定 / 数据字段定义 / 路径约定
- 若是，下面已跑过 grep 同步：
  - `grep -n "<旧描述>" PLAN.md` → 全部已改 / 留下 X 处合理保留（说明理由）

## 改动总结自我核查
- [ ] 改动总结里描述的数量、字段名、路径都与正文一致
```

---

## 7. 文档影响

修复完成后还需要同步：
- `docs/proposals/001-ai-decision-workbench-v4.md` ：暂不需要改（架构提案级别，未引用具体 schema 字段）
- `docs/004CHANGELOG.md`：建议加一条 `[2026-06-07-N] docs: fix v3.1 consistency issues [N1-N21]`
- `docs/003ISSUES.md`：无需开新 issue（v3.1 没有新 bug 流入实施，这是文档级清理）

---

**完成判定**：所有 21 条修订执行完毕 + 第 5 节"验收 grep 清单"11 条全部通过 → 关闭此提案。
