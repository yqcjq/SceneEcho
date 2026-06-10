# 010. Phase 1A 子能力重构 — 字幕 palette 模板级化 / 几何蒙版去字幕带误报 / 缩放方向加平移 / 新增 B-roll 子能力 / Lab 文件选择改造

**日期**：2026-06-10
**状态**：已决策
**关联 Issue**：ISS-019 / ISS-020 / ISS-021 / ISS-022 / ISS-023 / ISS-024

## 背景

阶段 2.6 完工、最小 MVP 跑通后，user 在 SubcapabilityLab 独立验证 Phase 1A 各子能力时，发现 6 处可识别的不足，已立 ISS-019..024。这些 issue 大部分需要修改 IR / 代码 / prompt 多处协同，必须先拍板"用什么方案"再分阶段实现。

具体压力来自：

1. 字幕样式 + 位置子能力的召回 + bbox 双低（ISS-019）。9.4s × 9 字幕样例上 captions 仅命中 4 条，且识别到的 bbox 普遍偏中下、只框 6 个字里 2 个。
2. 几何蒙版子能力把字幕带误识为矩形 mask（ISS-020）。同一样例上 mask 子能力把 9 个字幕首现位置全部当矩形蒙版报上来。
3. 缩放方向只能识别推/拉/稳/抖四类，覆盖不到 8 方向平移（ISS-021）。
4. 字幕功能分类的 IR 信息密度过低（ISS-022）。这不是"识别准不准"问题，而是"识别出的字段就不够用"——缺 shadow / background / padding / text_align / 完整 bbox 等视觉细节，跨 slot 共享同一字幕样式做不到，复用模板时只能拿到中文描述。
5. Phase 5 规划了 generate_broll，但 1A 当前没有任何"原样例哪段是 B-roll"的识别能力，下游没有可消费的字段（ISS-023）。
6. SubcapabilityLab fixture 列表硬编码、normalized.mp4 命名死板（ISS-024）。

四题切口由 user 在讨论中已选：CV 预扫文本带 + VLM 二次判定（不只是"加强 prompt"）/ 改 prompt + 砍 CV 矩形分屏检测 / 加平移 8 方向 / 模板级 caption_style_palette 重构（一次到位）/ 新增 b_roll 子能力但不接 generate_broll / dropdown 列已有 + file dialog 上传调现有 POST /samples ingest。User 也明确：caption / caption_function 不合并（两个维度：视觉模板 / 语义功能并存）；字幕动画细节子能力（captions_anim）保留现状不动。

## 被否定的方案

### 方案 A：CaptionStyle 字段扩充但不抽 palette

仅在现有 `CaptionStyle` 上追加视觉字段（shadow / background / padding / text_align / letter_spacing / line_height / bbox_norm），保留 `Slot.style.caption: CaptionStyle | None` 现有结构。改动局限于 IR + extract + renderer 三处，不需要动 apply / NL edit / 已存模板迁移。

否定原因：

- 同一模板里出现两种字幕样式（如顶部标题 + 底部 CTA）时，`Slot.style.caption` 被强制平摊到每个 Slot，相邻 Slot 共享同一种样式必须值拷贝；NL 编辑"把所有 CTA 字幕改成红色"需要遍历每个 Slot 改一次，无法在 palette 维度一次到位。
- "字段扩充 → 后期再 palette 重构"两阶段路线在数据迁移层会双倍成本：第一次扩充字段写一份 ir migration，第二次抽 palette 再写一份；且按字段扩充入库的模板还要二次迁移。User 明确"一次性做到位，不要分好几个阶段做"。

### 方案 B：合并 captions 与 caption_function 为一个子能力

User 起初反思过这两个维度是否重复。一种简化路线是把 `caption_function` 直接撤掉，仅由 `captions` 子能力的 `semantic_purpose` 字段一次性给出语义功能。

否定原因：

- User 二次思考后明确否决：画面字幕 ≠ 语音字幕（画面字幕被简化过）。同一段话在原样例画面里可能被编辑成短促 CTA 字幕 + 长说明字幕两种功能并存，与字幕的视觉样式正交——视觉样式应作为模板复用的核心，语义功能（含动画类型）作为另一维度独立判定。
- caption_function 还应升级承载"字幕动画类型"——这是 captions_anim 子能力（CV 微观验证）的语义化对偶，不属于"形貌"维度。

### 方案 C：把 mask 子能力重定义为人物轮廓分割

User 提到"几何蒙版对口播来说本质是人物轮廓的边缘变化"。一个激进方案是把 mask 子能力直接变成人物分割掩膜（接 SAM2 / RVM / MediaPipe-Selfie），由它取代当前的 VLM 判几何参数。

否定原因：

- 引入 SAM2 / RVM 是大依赖（GPU + 模型缓存），与当前 1A 全套技术栈错位（PLAN 视频理解技术选型已是 VLM 主路径 + 局部 CV 帮手）。
- 真几何蒙版（圆形头像框 / 特殊几何包装）虽然口播视频里少见但**不是零**——直接重定义会让"未来需要识别真几何蒙版"时失去能力。
- 当前 ISS-020 的核心问题是字幕带被误识，而不是"想识别人物轮廓"。重定义是借势改方向，超出本轮范围。

### 方案 D：Lab 页文件选择走拖拽 + quick-ingest 临时目录

让 Lab 页加拖拽框，调 `POST /api/lab/quick-ingest` 把 mp4 写到 `data/samples/lab_{ts}/source.mp4`，绕过现有 `POST /samples` 流程。

否定原因：

- 重复造轮子：`POST /samples` 已实现 normalize / metadata / 缩略图等完整 ingest 流程；新建 quick-ingest 端点会让两套 ingest 路径分叉，破坏"data/samples/ 下所有样例都是 ingest 后的成品"的不变量。
- 临时目录管理 / 清理是新增运维负担；user 选项 1（dropdown + file dialog 调 POST /samples）已能覆盖"想试任意 mp4"的体验诉求。

### 方案 E：caption_function 仅给 palette 元素打 function 标签，不发 per-caption 事件

Palette 重构后一种简化版是让 caption_function 仅对 palette 元素打标签（每个 palette 一行 function），不再发 per-caption 事件。

否定原因：

- User 强调"画面字幕 ≠ 语音字幕"——同一种视觉样式（同 palette index）在不同时间段可能承载不同语义功能（标题 vs CTA），平摊到 palette 会丢失这个时序维度。caption_function 必须保留 per-caption 视角。

## 最终决策

七个子决策一并拍板（按依赖先后排，每条均需要在 ARCHITECTURE / STRUCTURE / 渲染端 / 前端类型同步更新）：

1. **CaptionStyle palette 模板级化**（覆盖 ISS-022）
   - `TemplateIR` 加字段 `caption_style_palette: list[CaptionStyle]`，去重存储样例里出现的所有字幕样式。
   - `CaptionStyle` 字段扩充：新增 `shadow_color / shadow_offset / shadow_blur / background_color / padding / text_align / letter_spacing / line_height / bbox_norm: tuple[int,int,int,int]`（原 `position` 中心点保留兼容 + 显式 bbox）。
   - `Slot.style.caption` 改为 palette index：`Slot.style.caption_palette_idx: int | None`（None 表示该 slot 无字幕）。
   - Phase1ACaptionEvent 输出补全所有视觉字段；1B `skeleton.py` 改为先聚类（视觉 + 语义双信号）→ palette → Slot 引用 idx。
   - 应用阶段 `apply/style.py::apply_style` 通过 palette index 查 CaptionStyle，深拷贝走原有 emphasis_words 流程。
   - NL 编辑新增 op `update_palette_style(idx, field, value)`；prompt `2_5_nl_edit.md` 加示例。
   - 已存模板迁移脚本：扫 `kb.sqlite` / `template.json`，对每个旧 TemplateIR 把 `Slot.style.caption` 抽到顶层 palette 并改 idx；脚本一次性运行。

2. **CV 文本带预扫 + VLM 二次判定**（覆盖 ISS-019 召回部分）
   - `extract/captions.py` 加 `_detect_text_band_candidates(frame) -> list[bbox]`：Canny 边缘 + 形态学（横向 dilate 5×30）找"水平方向高对比度长矩形"作 ROI 候选；阈值偏向 false-positive。
   - VLM call 输入改为：每帧 ROI 候选 + 全帧缩略图 → VLM 仅做"该 ROI 是字幕吗 + 是字幕则给样式"二选一；漏掉的 ROI 由 VLM 自行回 "不是字幕"。
   - 子能力函数签名不变（`detect_captions(ctx, parent_event_id) -> tuple[list[Phase1ACaptionEvent], list[VisionEvent]]`），pipeline 内部多一道 CV 预扫；call_event 数量随 ROI 数变化，跨窗口合并按 IoU + palette_signature。

3. **修字幕 bbox 偏斜契约歧义**（覆盖 ISS-019 bbox 部分）
   - prompt `1a_captions.md`：删 `size_norm_0_999` 字段，仅保留 `position_norm_0_999: [x_left, y_top, w, h]`，并加一段 prompt 顶部明确说明 + 一组 in-context example（"位置示例：1080×1920 视频里底部居中的字幕带 [x=200, y=1500, w=680, h=120]"）。
   - 代码 `_bbox_from_pos_size`：保留对历史 4-元 / 2-元 + size 双格式的 fallback，但加 sanity check（w/h < 帧 5% 视为 estimate 异常，不接受）。
   - VLM 字号 estimate 偏小：prompt 加"font_size_px_estimate 是字符高度（不是 bbox 高度）"显式说明；后端 `_to_caption_style` 的 size 改为 `max(estimate, bbox_h * 0.6)` 兜底。

4. **几何蒙版去字幕带误报**（覆盖 ISS-020）
   - prompt `1a_masks.md`：在 system 段加显式排除项："字幕 / 标题条 / 水印 / logo / UI 元素**不算几何蒙版**；几何蒙版指给画面整体形状包装的几何区域（圆形头像框、分屏、矩形画框）。"
   - CV `masks.py`：删除 `_detect_rectangle` 与 `_detect_line_split`；保留 `_detect_circle`。CV 主路径仅对圆形蒙版有判定能力，其余形状全走 VLM 兜底。

5. **缩放方向加平移 8 方向**（覆盖 ISS-021）
   - `_ZoomDirection.direction` 枚举扩展为 `{推进, 拉远, 稳定, 抖动, 左移, 右移, 上移, 下移, 左上移, 右上移, 左下移, 右下移}`（13 类）。
   - VLM prompt `1a_zoom_direction.md` 加方向说明 + in-context example。
   - `motion.py::estimate_zoom_curve` 输出从 `list[ZoomKeyframe]`（仅 scale）扩展为 `list[ZoomKeyframe]`（加字段 `dx: float, dy: float`，归一化到帧宽/帧高）。LK 光流 keypoint 已有平均位移向量，改取均值 (dx, dy) 即可。
   - `VisualStyle.zoom_keyframes` 字段语义不变；ZoomKeyframe 增加 dx / dy 字段；渲染端 `ZoomLayer.tsx` 更新（消费新字段做 transform translateX / translateY）。

6. **新增「额外画面 / B-roll」子能力**（覆盖 ISS-023）
   - 新增 `backend/app/extract/b_roll.py` + `1a_b_roll.md` prompt。VLM 看每个 scene 的中间帧分类 `{人物主导, 全屏 B-roll, 画中画, 侧栏}` 四类 + 输出 ROI（如画中画 / 侧栏的 bbox）。
   - 写 `Phase1AReport.b_roll_segments: list[BRollSegment]`，含 `(start, end, kind, bbox_norm | None)`。
   - 1B `skeleton.py` 在 `_infer_material_req` 里加分支：scene 有 `kind in {全屏 B-roll, 画中画, 侧栏}` → `Slot.material_req = "AI生成画面"`。
   - **不接 generate_broll API**——Phase 5 真做时直接消费这个字段。识别 ≠ 启用 AIGC，与 D10 不冲突。
   - SubcapabilityLab REGISTRY 加 `b_roll` 条目。

7. **SubcapabilityLab 文件选择改造**（覆盖 ISS-024）
   - `lab.py::REGISTRY[*].fixtures` 字段去硬编码：改为运行时扫 `data/samples/`（含 `normalized.mp4` / `source.mp4` 的目录均算 fixture）。
   - 新增端点 `GET /api/lab/samples` 返回目录列表。
   - 前端 `SubcapabilityLab.tsx` dropdown 改为运行时拉取 `/api/lab/samples`；旁边加一个"上传新样例"按钮，触发浏览器 `<input type="file">` 选本地 mp4 → 调现有 `POST /samples` ingest → 完成后自动 select 并刷新 dropdown。
   - 「指标基线」面板**保留不动**（user 不投入精力做基线）；显示"尚未录入基线"是当前未填值，非 bug。

**交付节奏**（user 选"分阶段交付，每阶段独立可验证"）：

- 阶段 P1：IR 重构（template.py / phase1a_report.py / vision_event.py 字段扩充 + zod / TS 自动生成 + 已存模板迁移脚本）
- 阶段 P2：1A extract 重写（captions.py 加 CV 预扫 + bbox 契约修复；masks.py 删 CV 矩形/分屏；motion.py 加平移；新增 b_roll.py；prompt 全套更新）
- 阶段 P3：1B skeleton.py 适配 palette + 新 material_req 分支
- 阶段 P4：apply/style.py 通过 palette index 查 CaptionStyle
- 阶段 P5：renderer/Caption.tsx + ZoomLayer.tsx 适配新字段
- 阶段 P6：NL edit 加 palette 操作 op
- 阶段 P7：SubcapabilityLab 文件选择 UI + REGISTRY 去硬编码

每阶段在通过其子集 baseline + 工作台事件流人工走查后再启动下一阶段。任一阶段如发现方案不可行，回退仅影响该阶段及之后。

## 已知代价

### 代价 1：palette 重构对已存模板需迁移脚本，不可回滚
现有 KB 中已 ingest 的 TemplateIR 都按 `Slot.style.caption: CaptionStyle | None` 存储；palette 重构后必须跑迁移脚本才能继续被 apply pipeline 消费。脚本本身简单（提 caption + 去重 + 改 idx），但跑过一次后旧字段被覆盖，不能再回退到方案 A 的纯字段扩充路线。
**Followup**: ISS-022（迁移脚本作为该 issue 的子任务实施）

### 代价 2：CV 文本带预扫会增加每个 captions 任务的延迟
增加 CV 预扫 + 多次 VLM ROI 判定后，单个 captions 任务的延迟比纯 VLM grid 慢 50-150%（取决于 ROI 数）。当前 PLAN 1564 给的"单次 extract 端到端 ≤ 5 分钟"仍可满足，但单 fixture 调用延迟会从 ~10s 升到 ~20s。
**Followup**: 暂不追踪 — demo 阶段对延迟非约束（PLAN L46）；规模化部署时若再次成为问题再处理。

### 代价 3：删除 CV `_detect_rectangle` / `_detect_line_split` 后真实矩形/分屏 mask 完全靠 VLM
口播视频里几乎不出现真矩形 / 分屏 mask，但 PLAN 1444 的 `1A.masks` 仍保留"圆形 / 矩形 / 线分屏"三类。砍 CV 检测器后，矩形 / 线分屏只能由 VLM 兜底；如果未来某个非口播样例有真矩形 mask，VLM 单帧识别精度未必稳定。
**Followup**: 暂不追踪 — 项目定位明确为口播视频，非该域样例不属于本轮范围。

### 代价 4：新增 13 类 zoom direction 后 IR 字段语义膨胀
`_ZoomDirection.direction` 从 4 类升到 13 类，前端工作台事件染色 / 模板对比页面要相应扩展枚举展示；ZoomKeyframe 加 dx / dy 字段后渲染端 ZoomLayer.tsx 要重写 transform 计算（pan + zoom 联合变换）。
**Followup**: ISS-021（作为该 issue 的实施范围）

### 代价 5：caption_function 升级承载动画类型后，captions_anim 子能力的输出去向变化
captions_anim 当前直接写 `Phase1ACaptionEvent.verified_anim_in / stagger_ms`；升级后 caption_function 子能力会"消费 captions_anim 输出 + VLM 综合判 → 写 function + anim_type"，captions_anim 的字段从 IR 顶层退到 caption_function 的中间数据。该重构与 palette 重构同期完成。
**Followup**: ISS-022（与 palette 重构同期完成）

### 代价 6：SubcapabilityLab 上传按钮后样例数会无序增长
`data/samples/` 下的目录会因 lab 用户不停传新样例而膨胀；现有 `samples/{id}/source.mp4` 保留 90 天 cron 清理（PLAN L385）规则适用，但 demo 阶段可能很快堆到几十条。
**Followup**: 暂不追踪 — 90 天 cron 已能兜底；UI 加"删除样例"按钮属现有 SampleExtract 页职责，非本决策范围。

## 不在本期范围

- **人物轮廓 mask 子能力**（方案 C 的语义重定义）：用 SAM2 / RVM / MediaPipe-Selfie 给人物分割掩膜作为独立子能力。
**Followup**: future-plans/004-person-silhouette-mask.md
- **指标基线全套**（让 Lab 的"指标基线"面板真正能用）：每个 fixture × 子能力配人工 ground truth + 跑测脚本输出指标 + UI 绿/红显示。
**Followup**: 暂不追踪 — 工作量大于"修子能力本身"，且本项目 demo 优先级低；该面板暂保留显示"尚未录入基线"。
- **Phase 5 generate_broll 真接入**（消费 ISS-023 输出做 AI 生图 / 视频）。
**Followup**: 暂不追踪 — PLAN 阶段 5 已规划，沿原路径推进不属于本决策。
