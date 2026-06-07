# 001. 时间轴拖拽编辑器

**登记日期**：2026-06-05
**触发来源**：PLAN v2.3 重构时从主路线移出
**状态**：未排期

---

## 目标

为最终用户提供"多轨时间轴 + 块拖拽 + Player 同步预览"的可视化微调入口：当模板提取/应用结果不完美、分步审核与 NL 编辑不足以表达用户意图时，允许直接在时间轴上拖动 segment / Caption / Sticker / 转场。

---

## 价值判断

**为什么不放主路线**：
1. 与"模板自动套用"的核心价值有张力——时间轴的存在暗示"模板的自动产物需要手动救场"；分步审核 + NL 编辑 + 参数面板已覆盖 90% 的微调需求。
2. 前端工程量大——多轨时间轴 + 拖拽吸附 + 帧级时间换算 + Player 同步重绘的性能优化，工作量约为其他前端工作总和的 1.5 倍。
3. 没有清晰的最小可用版本——时间轴一旦上线，用户期待"完整剪映"，难以做"够用就行"的渐进交付。

**触发上线的条件**（满足其一即可考虑启动）：
- Phase 2/3 上线后，实际使用反馈显示 ≥ 30% 的项目需要事后手动调整 segment 边界 / Caption 时机 / Sticker 位置
- 模板库已 ≥ 30 个，且模板风格不够细的"通用模板"占比超过一半（提取保真度天花板触顶）
- 用户提出明确的、NL/参数面板无法表达的微调需求并能描述清楚

---

## 初步技术构想

**实现栈**
- 前端：React + dnd-kit（拖拽）+ 自绘时间标尺（canvas）+ wavesurfer.js（音轨波形）
- 状态：Zustand store 持有时间轴本地 view 状态，落地到 ProjectIR 通过 Patch
- 预览：复用 RemotionPlayer，timestamp 与时间轴 cursor 双向同步

**多轨设计**
- Track 1: 视频段（PlacedSegment）—— 块代表 `src_timerange` → `timeline_start`
- Track 2: 字幕（Caption）—— 块代表 `[start, end]`
- Track 3: BGM 音轨 —— 波形 + 节拍点
- Track 4: 贴纸（StickerEvent）—— 锚点 + 持续时间
- Track 5: Section 边界 + 过渡（Phase 4 后）

**操作 → Patch**
- 拖动块改 `timeline_start` → Patch op `move_segment`
- 拉伸两端改 `src_timerange` → Patch op `resize_segment`
- 双击删段 → Patch op `delete_segment`
- 右键菜单：复制 / 拆分 / 锁定（防误改）
- 操作的 Patch 与 NL / 参数面板共用 `patch_history`，可统一 Undo

**性能策略**
- 拖拽期间 Player 不重绘像素，仅移动 ghost overlay
- mouseup 触发 200ms debounce 后真正更新 ProjectIR + Player 重绘
- 时间轴大跨度滚动用 virtual list，单帧不渲染全部块

---

## 与主路线的依赖关系

- **依赖** Phase 2 已稳定（RemotionPlayer + ProjectIR + Patch 协议）
- **依赖** Phase 2.5 已稳定（patch_history / Undo）
- **不依赖** Phase 3 长视频闭环（短视频也能用时间轴）
- **互补** Phase 7 重排：时间轴可让用户在已重排基础上做更细的微调

---

## 已知风险与代价

- 性能：拖拽频率高时 Player 同步重绘可能卡顿，需要节流策略实测调优。
- 数据冲突：多块重叠 / Section 边界与 segment 边界冲突时的处理需要明确规则。
- 用户预期：上线时间轴后用户可能期待剪映级完整能力（关键帧编辑 / 滤镜面板 / 调音台），需明确"事后微调"定位、UI 上设引导。
- 工程量风险：估算 4-6 周专职前端 + 1-2 周后端配合，时间表必须独立而非塞入其他阶段。

---

## 待回答的问题（启动前需想清楚）

1. 时间轴是否要支持关键帧编辑（缩放曲线 / 字幕动画曲线）？
2. 时间轴 UI 库自研 vs 引入第三方？目前没有成熟的 React 时间轴拖拽组件库（Tldraw 太重，react-timeline-editor 不维护）。
3. 与 Phase 7 重排的优先级：用户先用 Phase 7 重排还是先用时间轴拖？
4. 是否暴露给所有用户？还是 power user 进阶模式？
