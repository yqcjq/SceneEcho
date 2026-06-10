# 011. 删除 1A.captions_anim 子能力，caption_function 承担动画语义；命名沿用 caption_function

**日期**：2026-06-10
**状态**：已决策
**关联 Issue**：ISS-022
**关联决策**：decisions/010-phase1a-subcap-rework.md（同日扩充）

## 背景

decisions/010 写完后 user 在 review 时进一步明确两点：

1. 字幕动画细节子能力（`1A.captions_anim`）应直接删除，其动画语义并入 `1A.caption_function`——动画类型本质是字幕"功能 / 行为"维度的一部分，不该作为独立子能力存在。010 决策 5 / 代价 5 给的是"captions_anim 保留但输出去向变化"的中间方案，user 否决该折中。
2. `caption_function` 是否改名为 `caption_template` 之类，曾被考虑——选择沿用 `caption_function`。

010 决策 1 引入 `caption_style_palette` 后，"字幕样式模板"语义由 palette 承担；`caption_function` 则承担"功能 + 动画类型"二维的字幕**行为元数据**。两个名字都叫"模板"会语义重叠，需要分名分职。

## 被否定的方案

### 方案 A：保留 1A.captions_anim，由 caption_function 消费它的输出（010 代价 5 折中方案）

captions_anim 仍走 CV 5fps 帧差 + Lucas-Kanade 光流路径产出 `verified_anim_in / stagger_ms`，写到 `Phase1ACaptionEvent`；caption_function 消费这两个字段做语义升级。

否定原因：

- captions_anim 当前识别准确率 user 反馈为"也不是非常正确"，且模板复用价值低（"字幕动画基本上在现有的几个里面随便选一个使用"）。继续投入 CV 微观验证收益不显著。
- 保留两个独立子能力让 IR 字段碎片化（动画字段挂 `Phase1ACaptionEvent`，功能字段挂 `Phase1ACaptionFunctionEvent`），caption_function 子能力还要从两份 IR 节点 join 数据，读取链路冗长。
- SubcapabilityLab 列表多一项几乎不会被点的子能力，体感噪音。

### 方案 B：caption_function 改名为 caption_template / caption_role

User 反思过 "function" 一词偏抽象，问是否改成 caption_template 之类的更直观名字。

否定原因：

- 010 决策 1 已用 `caption_style_palette` 承担"字幕样式模板"语义。`caption_template` 在中文翻译"字幕模板"上和 palette 完全重叠，违反"一个名字一个意思"。
- `caption_role` 是可选项但工作量大（stage 字面量 / prompt 文件名 / Python 模块名 / 工作台事件染色规则 / `scripts/check_stage_naming.py` 校验表全更名），收益不显著。
- `caption_function` 沿用现名 + schema 升级承载动画类型，语义清晰：function = 字幕扮演的功能（标题/CTA/...）+ 行为类型（anim_in/stagger）。Palette = 视觉样式模板；function = 行为元数据。两词互不重叠。

## 最终决策

1. **删除 `1A.captions_anim` 子能力**：
   - 移除 `backend/app/extract/captions_anim.py`
   - 移除 `backend/app/api/lab.py` 的 REGISTRY 中 `captions_anim` 条目
   - 移除 `Phase1ACaptionEvent` 的 `verified_anim_in / stagger_ms` 字段
   - SubcapabilityLab 列表少一项
   - PLAN.md 1417-1424 行 1A-V2 子能力描述同步删除（属 ISS-022 实施范围）

2. **`caption_function` schema 升级**：
   - 新增 `Phase1ACaptionFunctionEvent`：`caption_idx, function, anim_in_type, anim_emphasis, stagger_ms_estimate, role_in_template, confidence, reasoning`
   - `Phase1AReport` 加字段 `caption_functions: list[Phase1ACaptionFunctionEvent]`
   - VLM prompt `1a_caption_function.md` 升级为综合输出"功能 + 动画类型 + 关键词强调 + stagger 估计"
   - 名字 `caption_function` 沿用，不改名

## 已知代价

### 代价 1：stagger_ms 改由 VLM 估算，精度低于 CV 帧差光流
captions_anim 用 5fps 帧差 + Lucas-Kanade 给 ±30ms 精度的 stagger；caption_function 升级后由 VLM 看采样帧给"估计值"，精度可能 ±100-200ms。
**Followup**: 暂不追踪 — user 明确"动画基本可在几个标准类型里随便选一个使用"，stagger 精度不是关键复用维度；模板复用时按动画类型选预设动画，stagger 由渲染端按预设规则给定。

### 代价 2：PLAN.md 1A 节子能力清单 / 子能力依赖 DAG 需同步更新
PLAN 1A 节列出 11 个子能力含 captions_anim；本决策删一个，PLAN 应同步去掉该项 + 子能力依赖 DAG（PLAN 1516）移除 captions_anim 节点。
**Followup**: ISS-022（与 P3 caption_function 升级同期完成 PLAN 同步）
