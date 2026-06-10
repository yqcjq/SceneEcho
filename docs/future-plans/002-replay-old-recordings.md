# 002 — 回放 Phase 2.6 之前录制的 events.jsonl

**登记日期**：2026-06-10
**关联**：`decisions/009-phase2-6-replay-and-dual-axis.md` 代价 2

## 背景

Phase 2.6 的 `_build_event` 改为始终把 chat_vision 的结构化输出写入 `ir_value`（即使 `ir_target=None`）。这是 ReplayClient 用 schema 验证过滤队列的前置条件——它必须能从任何一条 chat_vision 事件复原结构化结果。

**存量数据问题**：项目在 v3.3 之前的多次 Phase 1A / 1B 跑批留下了 events.jsonl 文件，里面 captions / stickers 等子能力的 chat_vision 事件 `ir_value=None`（旧 `_build_event` 行为）。如果今天跑 ReplayClient 直接读这些旧 jsonl，会把它们当 `severity!="warning"` + `ir_value=None` 处理，按当前实现是 `continue` 跳过，最终 `ReplayExhaustedError`。

## 触发条件

满足以下任意一条时把这个规划提上议程：

- 用户明确提出"想用历史 events.jsonl 跑回归"——现实场景是某个 sample 一直没有重新跑过 extract，但其旧 jsonl 价值高（标志性 case）。
- v3.3 之前录制的 events.jsonl 数量 ≥ 5 且不容易重跑（如 ID 已被新 KB 覆盖、原视频已删）。
- 引入"长期"回归基准的需求（不只是最近一次录制）。

未触发前不动。

## 方案概述

写一个迁移脚本 `scripts/migrate_events_jsonl.py`：

1. 输入：一份旧 jsonl 路径。
2. 对每条 `stage` 起头是 `1A.captions` / `1A.stickers` 等已知 chat_vision 路径、且 `ir_value=None` 的事件，从同一 jsonl 后续事件里找它的实体级事件（`parent_event_id` 指向当前事件、`ir_target.path` 指向 entity append 路径），按其 `ir_value` 反向构造一份伪造的 `CaptionsRawResult` / `StickersRawResult` 写回 `ir_value`。
3. 写入新文件 `events_migrated.jsonl`，原文件保留。

不做就地改写——任何脚本错误都不会污染原始历史。

## 风险与依赖

- 反向构造的 `CaptionsRawResult` 字段不一定 1:1 还原原始 VLM 输出（实体事件已经做过 merge / refine），可能少了 reasoning / confidence 字段。
- 字段反向的逻辑跟 `extract/captions.py::_to_caption_entry` 强耦合；后者改了就要同步这边。

## 与当前实施的关系

当前实施：录制完整 events.jsonl 必须用 v3.3 之后的代码（`record_golden.py`）；老 jsonl 用不上 ReplayClient。Followup 落地后老数据可以参与回归。
