# 006. AIGC B-roll 视频生成 API 多 provider 选型与切换（推迟）

**登记日期**:2026-06-10
**触发条件**:Phase 5 B-roll 首版（ISS-028 单 provider 接入）跑通 1-2 周后，若实际使用中遇到下列任一情况，再启动本规划:

- 单 provider 调用成功率持续 < 80%（API 限流 / 排队 / 模型下线）
- 单条 B-roll 生成耗时 P99 > 5min,影响 demo 演示流畅度
- 单 provider 风格控制不足以覆盖样例模板的 dominant_lut_id（暖色 / 冷色 / 电影感等）
- 单 provider 计费突然涨价或限制商业用途，需要快速切换备选

## 背景

PLAN.md 2150 行 Phase 5 待讨论项明确列出"具体 API 选型（Runway / Sora / Kling / 即梦 / 自部署 SD-Video）"作为独立评估项。每个 provider 在以下维度有不同 trade-off:

| 维度 | Runway | Sora | Kling | 即梦 | SD-Video（自部署） |
|------|--------|------|-------|------|-------------------|
| 中文 prompt 友好度 | 中 | 中 | 高 | 高 | 取决于 LoRA |
| 单条延迟 | 30-90s | 5-15min | 60-180s | 30-90s | 取决于 GPU |
| 时长上限 | 4s / 10s | 60s | 5s / 10s | 6s / 15s | 取决于模型 |
| 风格控制 | 强（参考帧 / mask）| 中 | 中（多种风格预设）| 中 | 极强（LoRA 自训）|
| 商业授权 | 明确 | 限制 | 明确 | 中国版需求场景明确 | 自负（License 各异）|
| 单价 | $0.05-0.5 / 秒 | 估高 | 低（中国市场友好）| 低 | 仅 GPU 时 |

decisions/013 决策本期接入 1 个具体 provider 即可（够 demo 用），多 provider 抽象 + failover + cooldown / 余额警告推迟到本规划。

## 触发条件细化

满足以下任一即启动:

1. 实际使用反馈中"调用失败"成为高频问题（按周统计 ≥ 5 次）。
2. 项目准备走出 demo 阶段,迈向真实创作者工具(此时 vendor lock-in 风险变成业务风险)。
3. 出现单 provider 不能覆盖的样例风格类别(例如某模板的电影感调色需要 Runway 的 image-to-video 才能保留首帧色调,但当前接的 provider 不支持参考帧)。

## 实施依赖

- decisions/013 的 `agent/aigc.py` provider 抽象层已留好可扩展点(`AIGCBrollProvider` 抽象基类 + `get_broll_provider(name)` factory)。
- `Settings.aigc_broll_provider` 字段已存在,扩展为 list 即可。
- 新增 `agent/aigc/providers/{runway,kling,jimeng,sd_video}.py` 子模块,每个实现 `AIGCBrollProvider` 接口。
- 新增 `agent/aigc/router.py` 实现 failover + cooldown + 余额检查。
- `5.aigc.broll` 事件加 `provider` 字段供工作台展示当前实际调用的 provider。

## 不在本规划范围

- 自部署 SD-Video 的训练 / LoRA 数据准备(完全独立的工程线,需要 GPU + 标注数据)。
- 多 provider 内容审查能力对比与权重打分。
- 商业上的 vendor 谈判(技术决策外溢)。
