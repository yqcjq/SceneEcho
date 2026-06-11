# 014. ASR 文本与时间戳解耦：alignment 缺失时降级到等比兜底而非丢弃文本

**日期**：2026-06-11
**状态**：已决策
**关联 Issue**：ISS-031

## 背景

决策 012 把 `_glm_pipeline` 设计成「GLM-ASR 拿文本 + WhisperX wav2vec2 拿字级时间戳」的串联管道。这条链有一个隐含约束：alignment 这一步必须依赖 `whisperx`（同时拽进 torch、wav2vec2 中文对齐模型 ~1.2 GB）。

实测中两件事一起把这条链推进了死角：

1. `whisperx` 与 `torch` 既没有写进 `backend/pyproject.toml` 的主依赖，也没有进 `[extract]` extras——执行决策 012 时只改了代码、没改 dep 声明。
2. 用户机器是 Windows + 无 GPU，新装 torch + whisperx 的成本高、容易翻车（pyaudio / soundfile / triton 等链式依赖在 Windows 上经常出问题）。

直接表现：用户在 Editor 全流程跑下来，`recommend_templates_endpoint` 写出的 `projects/{pid}/transcript.json` 全是 `{"text": "[语音 0]", ...}` 占位符（在 `data/projects/prj_381c792265/transcript.json` 现场确认），`apply_short` 复用同一份 ledger 后下游 mapping → style → Caption 全部基于占位文本，工作台 IR 树和最终成片字幕都看到 `[语音 N]` 而非真实台词。

排查显示 GLM-ASR 接口本身完全正常——直接对 `https://api.ppio.com/v3/glm-asr` POST 一个从 `tests/fixtures/raw_10s/start10s.mp4` 提取的 wav，HTTP 200 + 返回完整中文转写「对于普通大学生来说，综测才是第一外挂。…」。失败发生在拿到文本之后：`_align_text_only` 的 `import whisperx` 抛 `ModuleNotFoundError`，整个 `_glm_pipeline` 被判失败，**已经在手的 GLM 文本被丢弃**，外层降级到 `_whisperx_run`（同样 `ImportError`），再降级到 `_fallback_uniform_chunks` 把占位符写进盘。

第一性原理上这是一个耦合 bug：**文本提取和时间戳标注是两件独立的事，不应被同一条 fallback 链绑定**。文本是真理源（Caption.text 由 D11 绑死等于 Unit.text），丢文本就等于丢声音；时间戳只决定 Caption 的起止时刻，精度差一点不会让用户看不懂。

## 被否定的方案

### 方案 A：把 `whisperx` + `torch` 写进必装依赖

否定原因：torch 在 Windows + 无 GPU 上是 ~1.5 GB CPU 轮子（带 CUDA 是 ~3 GB），叠加 wav2vec2 中文模型首次拉 ~1.2 GB，光 ASR 一项就把 base install 体积推到 ~3 GB。SceneEcho 是单人/小团队的实验项目，base install 应该 5 分钟内跑通。让全部用户为「字级时间戳从 ±0.2s 漂移降到 ±0.05s」付这个体积代价不成比例；况且决策 012 已经把 whisperx 标过「offline 兜底」而非主路径，主路径走 GLM-ASR 网络调用。

### 方案 B：换上云 Whisper API 一次拿到文本+时间戳

否定原因：实测验证 PPIO `https://api.ppio.com/v3/glm-asr` 的 OpenAPI schema 响应只有 `{"text": "..."}` 一个字段，不带 segments/words/任何时间戳；查 `https://ppio.com/docs/models/reference-glm-asr` 也确认仅 text。换原生智谱 BigModel 需要单独申请并管理一套与 PPIO 隔离的 API key，凭据管理面双倍。Phase 2 当前没有可用的「云 ASR + 时间戳」端点，本地对齐这一步省不掉。

### 方案 C：删掉 wav2vec2 路径，永远只用等比对齐

否定原因：`_whisperx_run` 这条腿对 offline / 无 PPIO 凭据 / 音频 > 30 s 这些场景仍是兜底（决策 012 代价 1 / 3 已声明），删掉后这些场景没有降级出口。等比对齐是「字级精度」的合理 graceful fallback，不是 wav2vec2 的等价替代——完全替换会留下 Phase 3 长视频上没有 ASR 引擎的设计缺口。

### 方案 D：改 fallback 顺序，让 Layer 2（whisperx 自闭环）能拿到 GLM 文本继续工作

否定原因：本质上还是把文本绑死在某条 alignment 引擎上，没解决「文本 vs 时间戳」耦合的根因；只是换了一种耦合形式，第一性原理上没改进。

## 最终决策

把 `_glm_pipeline` 内部的 alignment 步骤从「单条腿」改成「双腿」：

```
_glm_pipeline(media):
    1) ffmpeg → wav (16kHz mono)
    2) transcribe_glm(wav) → text   ← 真理源,失败才升 GLMASRError
    3) align text:
       try   _align_text_only(wav, text)   # Leg A: wav2vec2(whisperx + torch)
       except → _proportional_alignment(text, duration)   # Leg B: 等比兜底
    4) _segments_to_units(segments)   ← 同一切分器消费两腿
```

关键约束：步骤 3 的 `except` 只捕获 alignment 异常，**不让异常沿调用栈往外冒到外层 transcribe()**；外层 transcribe 的三层降级（GLM → WhisperX 自闭环 → uniform chunks）只在「连文本都拿不到」时启动。这样：

- GLM-ASR 200 OK → ledger 拿到真实文本（精度跟 alignment 选哪条腿无关）
- GLM-ASR 失败 (4xx / 网络 / 凭据缺失) → Layer 2 接力（仅当本机装了 whisperx 才有产出）
- Layer 2 也失败 → Layer 3 写 `[语音 N]` 占位（占位真正的语义是「我们没听到任何声音内容」）

新增 `_proportional_alignment(text: str, duration_sec: float) -> list[dict]` 纯函数：把 text 切成单字符列表（中文一字一 token，符合 wav2vec2 中文对齐的字符粒度），按 `duration_sec / len(chars)` 把每个字均匀分布到时间轴；输出 WhisperX 兼容的 `[{text, start, end, words: [{word, start, end, probability}]}]`，让 `_segments_to_units` 无差别消费。`probability=0.6` 标记等比来源；切分器的「中文标点 + UNIT_MAX_CHARS」两条规则在等比 segments 上完全照常工作（GLM-ASR 自带「，。」标点），「一标点一字幕、4-12 字一片」颗粒度立刻达标——实测 8s 短口播 19 字 → 切出 8 个 Unit。

事件层面新增 `stage="2.asr.glm.align_proportional"` `severity="info"` 的 VisionEvent：每次走 Leg B 都发一条，工作台中栏可以直接看见「本次时间戳是等比近似而非 wav2vec2 字级」，让用户对精度知情。

ASR 总入口的三层降级链结构不动（避免决策 012 的核心拓扑出现「实施落地后修订」漂移），只在 Layer 1 内部增加 alignment 的二级降级；`_whisperx_run` / `_fallback_uniform_chunks` 接口与触发条件保持决策 012 的样子。

## 已知代价

### 代价 1：等比对齐在不均匀语速下时间戳漂移加大

口播节奏起伏（如停顿强调、加快语速）时,等比给每字相同时长会和真实发声偏离 0.1-0.3 s/字累积。Caption 起止与画面 lip-sync 在视觉上能看出错位。短口播（≤ 20 s）+ 普通匀速朗读这类 Phase 2 主流场景影响不显著；长视频不可接受。
**Followup**：暂不追踪 — Phase 2 ★MVP 范围就是 ≤ 20 s短口播,精度容忍区内;Phase 3 长视频规划阶段会重新评估「装 whisperx」/「换流式 ASR API（云端自带字级时间戳）」/「LLM 后处理对齐」三条路。

### 代价 2：所有用户都默认走 Leg B,wav2vec2 高精度路径事实上很难被启用

只要本机不装 whisperx,Leg A 永远 ImportError、永远走 Leg B。决策 012 想让 wav2vec2 是 happy path 的目标实际上还没达到——决策 014 把这件事公开化：默认 base install 不含 whisperx,精度按等比走;高精度需要用户额外 `pip install whisperx torch torchaudio`,并且接受这是高级用户路径。
**Followup**：暂不追踪 — 这是「不把重 ML 写进必装」的必然代价,与代价 1 同一权衡;PLAN 后续讨论「offline 高精度可选 extras」时再议。

### 代价 3：GLM-ASR 30 s 上限继承自决策 012 未变

PPIO `glm-asr-2512` endpoint 单次 ≤ 30 s / 25 MB,Phase 3 长视频仍需分块或换后端。
**Followup**：暂不追踪 — 与决策 012 代价 1 等价,不重复登记。

### 代价 4：proportional alignment 的 `probability=0.6` 让 `_segments_to_units` 算出的 `Unit.avg_logprob` 偏低（约 -0.5）

下游有 PLAN 提到的「avg_logprob < -0.6 标 low-confidence」UI 标记;等比 Unit 的 avg_logprob 在阈值边缘,可能偶发 false-low confidence 报警。当前没有用户可见的 low-confidence UI（Phase 2 还没接此 UI 标记）,所以不会立刻表面化。
**Followup**：暂不追踪 — Phase 2 没有消费 avg_logprob 阈值的 UI 路径;Phase 2.5+ 真接入 UI 标记时如果发现误报多,届时重新评估等比 segments 的 probability 值或增加 alignment_method 字段直接区分。
