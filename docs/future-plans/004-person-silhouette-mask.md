# 004. 人物轮廓 mask 子能力（替代或并存于几何蒙版子能力）

**登记日期**：2026-06-10
**状态**：已识别 · 暂不实施
**关联决策**：decisions/010-phase1a-subcap-rework.md

## 背景

decisions/010 在讨论 ISS-020（几何蒙版子能力误把字幕带认成矩形 mask）时，user 提出过一个语义重定义方向："对口播视频来说，几何蒙版本质就是人物画面边缘轮廓的变化"。这是一个比"砍 CV 矩形分屏检测"更激进的改造——把 mask 子能力的语义从"画面里有没有圆/矩形/分屏几何形状"改成"画面里人物的分割掩膜随时间如何变化"。

decisions/010 已选择保守路径（方案 C 被否定），仅清理字幕带误报；但这条改造方向价值真实存在，作为远期演进项登记。

## 触发条件

满足以下任一条件时启动实施讨论：

- Phase 5（AIGC 扩展）落地后，"人物前景 + AI 生成背景"的画面合成需求出现，需要精准的人物分割边界做 alpha matting。
- 用户在演示中明确反馈"想做基于人物边缘的特效"（环境光晕 / 边缘描线 / 背景虚化等）。
- decisions/010 的方案 4（删 CV 矩形/分屏 + VLM 兜底排除字幕）跑了一段时间后，出现真正想识别人物轮廓但被误判为"无几何蒙版"的情况。

## 候选技术路线

不在本登记范围深入，仅列出可能选项：

- SAM2（Meta Segment Anything Model 2）：通用分割能力强，需 GPU；可作 promptable 分割接受 user click。
- RVM（Robust Video Matting）：专做视频人物 matting，输出 alpha 通道；轻量但精度略低于 SAM2。
- MediaPipe Selfie Segmentation：浏览器友好、CPU 即可跑、精度中等。

实施时再做选型对比；现阶段不预判。

## 与现有架构的关系

- 不替代 decisions/010 的几何蒙版子能力——并存为独立子能力 `1A.person_silhouette`。
- IR 层新增 `Phase1AReport.person_masks: list[PersonMaskFrame]` 或类似字段；不挤占 `Phase1AMaskParams` 的语义空间。
- 渲染端需要新组合 `compositions/PersonMask.tsx`（或扩展 `Mask.tsx` 加分支）。

## 暂不实施的理由

decisions/010 已知代价 3 与不在本期范围 1 已说明。简记：当前 demo 优先级在子能力准确率修复（特别是字幕重构），人物分割是另一条独立工作流，不混在本轮做。

## 状态变更历史

- 2026-06-10：登记，由 decisions/010 触发。
