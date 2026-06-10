# 008. Phase 2.5 ProjectIR 编辑链路存储 — Snapshot 栈 + events.jsonl 作为 Patch 真理源 + 轻量级渲染节流

**日期**：2026-06-09
**状态**：已决策
**关联 Issue**：ISS-015

## 背景

阶段 2.5（PLAN 1666-1759）要求引入 NL 编辑 / 参数面板 / Undo / 编辑历史四件套，每次编辑都把 ProjectIR 走 Patch 流程改写并触发重渲染。PLAN 原文（1684-1689 + 1702）含三个具体设计：

1. `undo` 通过反向计算每条 patch 的逆操作回退（per-op inverse）；
2. patch 历史除了 events.jsonl 外再单独写一份 `patch_history.jsonl`；
3. 渲染节流新增独立模块 `backend/app/agent/render_queue.py`。

实施时发现三处都和当前 SceneEcho 已建好的抽象正面相撞——事件总线（D9 / D10 / D11）已经做了"事件即真理源"的工作；渲染队列（D7）已经是单 worker 串行。如果按 PLAN 字面落地，会引入两套并行的真理源 + 一层冗余抽象，恰好是 README "不得继续在原有逻辑上打补丁" 要踩死的反模式。

## 被否定的方案

### 方案 A：per-op 反操作 undo

PLAN 原文方案。`apply_patches` 只走 forward，undo 时再为每个 op 实现 inverse 函数。

否定原因：

- PatchOp 枚举有 11 项（`set_caption_style` / `swap_template` / `adjust_rhythm` / `delete_segment` / `set_emphasis` / ...），且 PLAN 后续 Phase 6 还要新增 `reorder_sections`（PLAN 2217）。每加一个新 op 必须同步加一个 inverse 函数，且 inverse 必须存"被覆盖前的旧值"（如 `swap_template` 反向要知道 OLD template_id）。
- 旧值不在 Patch.value 里——必须在 forward 时额外采集存储，相当于 forward 路径额外背一个 inverse 记录的负担。
- 多个 patch 组成的 mega-patch（PLAN 2217 的 `reorder_sections` 是显式提到的复合 patch），inverse 需要按倒序重放并彼此组合，逻辑复杂度二次方膨胀。
- 任何 inverse 实现 bug 都会让 ProjectIR 静默漂移（apply N 次 → undo N 次 → 不回到初始状态），且不容易被单测覆盖（要 N×M 组合）。

### 方案 B：patch_history.jsonl 作为 Patch 真理源（并行 events.jsonl）

PLAN 原文方案。`apply_patches` 内部 append 写一份 `projects/{id}/patch_history.jsonl`；同时 `nl_edit` 还往 events.jsonl 发 `stage="2.5.nl_edit"` 的 VisionEvent（PLAN 1681）。

否定原因：

- 同一条 Patch 必须出现在两个文件里，且两份必须保持同步——一旦 nl_edit 流程在两个 write 之间抛错就形成"半同步"状态（events.jsonl 有，patch_history 无 / 反之）。
- D10（events 持久化按资源 kind 路由）已经把 jsonl 当作 EventBus 的真理源（sequence high-water mark / SSE replay snapshot）。再引入一份 patch_history.jsonl 等于给 ProjectIR 装第二个真理源，破坏 D1（IR 是地基，单一真理源）的衍生约束。
- Phase 2.5 验证 5（PLAN 1753）的工作台事件回放本来就读 events.jsonl，从中按 `stage` 过滤即可拿到 Patch 流——根本没有 patch_history.jsonl 才能完成的功能。
- 文件多一份意味着 cleanup / 备份 / 同步迁移多一条规则；ROI 为零。

### 方案 C：独立 render_queue.py 模块管理项目级节流

PLAN 原文方案。新增 `backend/app/agent/render_queue.py` 模块，实现项目级队列 + cancel / supersede 状态机。

否定原因：

- D7 已经声明渲染队列单 worker；renderer 端 `p-queue({concurrency:1})` 串行执行。所谓"3 次 NL 编辑 100ms 内触发 3 次 render"的真问题是"队列堆积"而不是"并发冲突"——堆积可以用一个 `project_id → in_flight_task_id` 字典 + asyncio.Lock 解决，~30 行代码。
- 抽出独立模块意味着要定义状态机（pending / running / superseded / cancelled / completed / failed）、暴露 API、写测试 fixtures、再补一层 schema。MVP 阶段引入这层抽象只为承载 30 行的核心逻辑，违反"先做对，再抽象"。
- 当未来真的需要队列优先级 / 多 worker / 跨 project 并发限速时，再从 `render/throttle.py` 升级到独立模块，回报曲线更划算。

## 最终决策

三个子决策一并落地：

1. **Snapshot 栈代替 per-op inverse**。`apply_patches` 之前先 `push_snapshot(project_id, ir_before)` 把当前 `project.json` 拷贝到 `projects/{id}/snapshots/v{N}.json`（N = 拷贝时刻的 `ProjectIR.version`）；`undo()` 从最新版本号开始读最高 v{N}.json 写回 project.json 并删除该文件。新增 PatchOp 不需要触动 undo 实现。
2. **events.jsonl 作为 Patch 单一真理源**。每个成功 patch 同时发一条 `stage="2.5.nl_edit"` VisionEvent，写入对应 task（kind 为 `nl_edit` / `panel_edit`）的 events.jsonl。`GET /projects/{id}/history` 查 `tasks WHERE kind IN ('nl_edit','panel_edit') AND resource_id={id}` 后逐 task 读 jsonl 过滤 stage 即得 Patch 流。无独立 `patch_history.jsonl` 文件。
3. **轻量级渲染节流**。`backend/app/render/throttle.py` 暴露 `trigger_render_supersede(project_id, task_id, ir)`，用 `defaultdict(asyncio.Lock) + dict[project_id, task_id|None]` 串行化"取出旧 + 设置新"；旧任务存在时调 renderer 的 `DELETE /render/{tid}`（renderer 端在 `queue.ts` 加 registry，pending 任务直接 skip，running 任务标 cancelled）。

## 已知代价

### 代价 1：snapshot 文件占用磁盘

每次 NL/panel 编辑都写一个 v{N}.json（典型 ProjectIR ~5-50 KB）。长会话 100 次编辑 ≈ 5 MB / project。

**Followup**：暂不追踪。MVP 阶段单用户单 project 实测下显著低于 video 资产体积；Phase 7+ 多用户 SaaS 化时再加 snapshot 上限（保留最新 N 个）。

### 代价 2：snapshot 文件名与 ProjectIR.version 字段强绑定

`push_snapshot` 用 `ir_before_apply.version` 作为文件名。如果有人绕开 `api/edit.py` 直接手改 `project.json` 把 version 字段改成已存在的值，下一次 push 会覆盖该 snapshot。

**Followup**：暂不追踪。"绕开 API 直改 IR" 本身是程序员错误；apply / nl_edit / undo 内部都使用同一对 push/undo 接口，正常路径没有该风险。

### 代价 3：events.jsonl 同时承载多种 stage（apply / extract / nl_edit / panel_edit），history 端点要做客户端侧过滤

`list_patch_history` 必须扫所有 nl_edit / panel_edit task 的 events.jsonl + 按 stage 过滤，O(task 数 × 平均 jsonl 长度)。

**Followup**：暂不追踪。MVP 规模 task 数 ≤ 200，平均 jsonl ≤ 50 条；扫一次 < 100ms。Phase 7+ 需要时加 stage 字段索引或物化视图。

### 代价 4：renderer 端 cancel 是"软取消"——已开始渲染的任务无法真停止

`p-queue` + Remotion 渲染中无法干净中断 Chromium 进程；我们只把任务标 cancelled 并在 onProgress 回调时报告 `status=cancelled`，但 Chromium 仍跑完当前 chunk 才释放。最坏情况 = 一次最长 30s 的"白渲"。

**Followup**：ISS-016（如未来出现）追踪"真硬中断"——需引入 `process.kill(child_pid)` 直接 SIGKILL Remotion 子进程，需在 renderer 跨平台路径上验证；MVP 不做。

### 代价 5：panel_to_patches 的字段表是写死的字符串

新增参数面板控件必须同步在 `panel_to_patches` 的 if-elif 链中加一条。

**Followup**：暂不追踪。控件总数 ≤ 20，加一个 panel 控件本身也只需改一处 UI，translator 和 UI 改动等价，没有合理的解耦点。
