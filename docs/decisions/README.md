# 架构决策记录（Decisions / ADR）

本目录存放**已拍板的重要架构决策**，每份文件回答一个问题：

> 当时为什么这么决定？否定了哪些方案？

## 用途

为以下情况留下不可丢失的推理链路：

- 涉及模块间协作方式、调用链、数据流的变动
- 涉及技术选型（用 A 不用 B，且有多个可选方案）
- 一旦实施后难以回退，或回退成本很高
- 有多个方案被认真讨论过，最终否定了其中一个或多个

不属于决策的情况（直接跳过）：

- 单个 bug 修复，原因明确，没有方案选择
- 改变量名、调整日志格式、补注释等局部改动
- 方案从一开始就只有一个，没有任何分叉

## 写作风格

**有立场，记录推理，重点写"否定了什么"。**

像法庭判决书——必须说清楚推理链，尤其是为什么排除了其他选项。

每份文件使用以下固定格式（字段顺序不可调换，详见 `../000README.md`）：

```
# NNN. 标题（一句话描述这个决策）

**日期**：YYYY-MM-DD
**状态**：已决策 | 已实施 | 待实施 | 待优化 | 已废弃（被 NNN 取代，YYYY-MM-DD）
**关联 Issue**：ISS-NNN

## 背景
当时面临什么具体问题。只写"是什么逼着我们必须做这个决定"。

## 被否定的方案
### 方案 A：方案名称
否定原因：客观约束或已验证的问题，不接受"感觉不好"。

### 方案 B：方案名称
否定原因：同上。

## 最终决策
选择了什么，一句话说清楚。不写"这样更好"——优点已通过否定其他方案隐含证明。

## 已知代价
我们知道并接受的副作用。
```

约束：

- 不写泛泛的优点（"这样更清晰"——无效信息）
- 不写"未来可以考虑"（应在 `../003ISSUES.md` 开条目）
- 已写入的决策不修改，只新增
- `关联 Issue` 字段指向触发这个决策的 ISS 编号

## 与其他文档的区别

| 文档类型 | 性质 |
|---------|------|
| `../001ARCHITECTURE.md` | **当前系统的客观事实**，不解释原因 |
| `../003ISSUES.md` | **已发现的问题**，等待修复或讨论 |
| `decisions/`（本目录） | **已拍板的决策**，记录推理与被否定的方案 |
| `../future-plans/` | **已识别但暂不实施的演进方向** |

## 命名约定

`NNN-<topic-slug>.md`，编号按拍板顺序递增。已写入的决策永不重命名、永不删除——`004CHANGELOG.md` 与 `003ISSUES.md` 通过文件名引用本目录条目，重命名会断引用链。

被后续决策取代的旧决策保留在原位，状态字段标注关系（如 005 头部声明"取代 003 / 004 的实施部分，003/004 保留作为演进历史"）。

## 判断标准

六个月后看这份文件，能否清楚知道**为什么不能走回头路**。核心问题永远是：当时为什么没选方案 B？

## 现有决策

- [001 — Agent 调度器采用 dataflow + 按物理设备加锁](001-agent-scheduler-dataflow-model.md)
- [002 — 执行控制事件订阅从 Screen 级提升到 App 级](002-execution-control-global-subscription.md)
- [003 — 主 Agent 决策日志采用结构化 + 精简模型](003-agent-decision-log-context-structure.md)（已废弃，被 005 取代）
- [004 — 主 Agent 决策上下文重新设计](004AGENT-CONTEXT-REDESIGN.md)（已废弃，被 005 取代）
- [005 — 主 Agent 决策上下文 V3：从"记录"转向"决策"](005AGENT-CONTEXT-DECISION-MODEL.md)
- [006 — 主 Agent 后台展示层重构](006-admin-visualization.md)
- [007 — 主 Agent 通过心跳信号进行 Step 级 liveness 检测](007-step-liveness-via-heartbeat.md)
- [008 — AI System Prompt 按调用情境分离为三份独立 prompt](008-ai-prompt-split-by-context.md)
- [009 — AI 工具集合按"原子 + 可观察 + 必要"三原则收敛](009-ai-tool-set-rationalization.md)
- [010 — Schedule 从 Task 字段解耦为一等实体](010-schedule-entity-decoupled-from-task.md)
- [011 — AI 顶层短等待原语 Wait + 心跳冻结 STEP_TIMEOUT 机制](011-ai-wait-primitive-with-step-timeout-freeze.md)
- [012 — AI 用户检查点原语 UserGate（含统一的用户确认 UX）](012-ai-usergate-primitive.md)
- [013 — AI 任务委托与调度原语族（CallTask / ScheduleTask / UnscheduleTask）](013-ai-task-delegation-and-scheduling-primitives.md)
- [014 — AI 工具注册表 — 单一来源 + 局部代码生成](014-tool-registry-single-source.md)
- [015 — GitHub Actions 阶段 1 CI — 确认触发条件与最小范围](015-ci-pipeline-stage1.md)
- [016 — agent 线协议前后端字段同构——pytest 接入 model_json_schema](016-agent-contract-parity-test.md)
- [017 — SendReminder / CancelReminder AI 原语与 Android 通知 channel 集中管理](017-send-reminder-notification-channel-system.md)
- [018 — SendReminder 时间参数从绝对 triggerAtMs 改为相对 delayMs](018-send-reminder-delay-ms.md)
- [019 — admin agent_detail 信息密度与单页诊断动线重排](019-admin-agent-detail-ux-pass2.md)
- [020 — DecisionEvent 增加 raw_response 字段并升级展示](020-decision-event-raw-response-and-visualization.md)
- [021 — 测试 pipeline 数据模型与后台合并 — 复用生产 AgentSession，新增 4 张测试元数据表](021-test-pipeline-data-model-and-merge.md))
- [022 — Server-originated agent.goal 链路 — 抽出公共函数复用主路径，删除 admin debug 端点](022-server-originated-agent-goal.md)
- [023 — 全链路 AI 调用 token/cost 追踪 — 新建价格表 + 三类调用点写入 + AgentSession 原子累计](023-ai-call-token-cost-tracking.md)