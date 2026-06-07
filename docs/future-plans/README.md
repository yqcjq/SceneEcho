# 远期规划（Future Plans）

本目录存放**现在有想法、但本期不实施**的规划文档。

## 用途

记录已被识别但因下列原因暂不落地的方案：

- 复杂度跳跃过大，当前阶段没有匹配的真实场景需求（YAGNI）
- 触发条件未到（如"用户量增长到 X"、"出现 Y 类需求"）
- 当前架构层级尚未稳定，过早实现会被新设计推翻

每篇文档应包含：

1. **背景** — 从哪个 Issue 或讨论中诞生
2. **触发条件** — 什么情况下应该把这个规划提上议程
3. **方案概述** — 当前已构思的实现轮廓（不必完整，避免过早绑定细节）
4. **风险与依赖** — 实施前需先解决的前置项
5. **与当前实施的关系** — 当前用什么方案兜底、未来切换路径

## 与其他文档的区别

| 文档类型 | 性质 |
|---------|------|
| `003ISSUES.md` | **已发现的问题**，等待修复或讨论 |
| `decisions/` | **已拍板的架构决策**（ADR） |
| `future-plans/`（本目录） | **已识别的演进方向**，但暂不实施 |

## 命名约定

`NNN-<topic-slug>.md`。编号是登记顺序，**不代表优先级或时序**。

## 现有规划

- [001 — System Prompt 数据库管理 + 后台可视化](001-system-prompt-db-management.md)
- [002 — Admin 后台前端工程化重构](002-admin-frontend-modernization.md)
- [003 — Admin 高级诊断分析功能](003-admin-diagnostic-analytics.md)
- [004 — CI 流水线 + 自动化质量门禁](004-ci-pipeline.md)
- [005 — AI 指令注册表单一来源 + 代码生成](005-tool-registry.md)
- [006 — 屏幕全文提取（取代 SelectAllAndCopy 的真实意图）](006-screen-text-extraction.md)
- [007 — 会话级记忆系统](007-session-memory-system.md)
- [008 — Android 系统通知接口（AI 主动提醒类指令）](008-android-notification-reminder.md)
- [009 — ai_module 状态持久化 + alarm 唤醒长挂起](009-ai-module-suspend-resume.md)
- [010 — 测试 pipeline 演进方向](010-test-pipeline-extensions.md)
