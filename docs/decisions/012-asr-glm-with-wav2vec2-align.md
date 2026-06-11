# 012. Phase 2 ASR 后端切换：GLM-ASR 高精度文本 + WhisperX wav2vec2 强制对齐

**日期**：2026-06-10
**状态**：已决策
**关联 Issue**：ISS-027

## 背景

User 在 Phase 2 出片闭环中观察到三个相关问题，均围绕 ASR 链路：

1. WhisperX large-v3 中文识别同音字错误明显（user 原话："基本上是同音不同字的错别字"）。Caption 链路 D11 硬规则 `Caption.text == Unit.text`，下游无纠错环节，所以 ASR 错什么字最终就是什么字。
2. 一段 8 秒、约 100 字的口播只产出**一条**静态字幕、横跨整个视频时长。已确认根因是 `_UNIT_GAP_SEC=0.3` 远大于流畅口播实际词间停顿（多数 < 0.15s），所有词被合并为单个 Unit；style.py 一 Unit 一 Caption，所以最终只有一条字幕。
3. 推荐阶段已经跑过完整 ASR、ledger 摘要喂给 VLM 后整段 ledger 用完即丢；Apply pipeline 进 ASR 阶段时再调一次 `transcribe`，对同一份 normalized.mp4 重跑 WhisperX 浪费 3-5s。

User 要求"模板到出片"路径按第一性原理优化，关键诉求是**字幕识别准确率**与**一停顿一字幕、4-12 字一片**的颗粒度。

## 被否定的方案

### 方案 A：仅调小 _UNIT_GAP_SEC + 升级 WhisperX 到 large-v3

否定原因：解决了切句颗粒度但解决不了同音字。WhisperX 中文 CER 在 12-15% 量级，同音字错误对最终字幕观感影响远大于切句节奏。User 已明确字幕准确率是核心痛点。

### 方案 B：MiniMax 语音 API

否定原因：查阅 MiniMax 官方文档与 PPIO 模型目录，MiniMax 公开 API 仅有 TTS / 视频 / 音乐生成，**未提供 ASR 接口**。User 报告"主要有 minimax 和 GLM 的模型"中可用的 ASR 资源只有 GLM-ASR-2512。

### 方案 C：智谱 BigModel 原生 multipart upload

否定原因：原生 endpoint `https://open.bigmodel.cn/api/paas/v4/audio/transcriptions` 需要单独申请并管理智谱原生 API key，与项目现有 PPIO 中转 key 隔离两套凭证。PPIO 已通过 `https://api.ppio.com/v3/glm-asr` 代理 GLM-ASR-2512，复用现有 `LLM_API_KEY` 即可，凭证管理面更小。

### 方案 D：纯 audio LLM 不做对齐 — 直接信任 LLM 自带句级时间戳

否定原因：GLM-ASR-2512 响应 schema 仅 `{"text": "..."}`，无任何时间戳字段（segments / sentences / words 都没有，已逐字段验证 OpenAPI 定义）。"用 LLM 自带句级时间戳"在该 endpoint 下不存在。

### 方案 E：完全替换 WhisperX、不保留本地路径

否定原因：GLM-ASR 30s/25MB 上限会拦截 Phase 3 长视频（~3min）；离线 / 网络受限 / PPIO 配额耗尽场景需要可降级路径。WhisperX 仍作为 fallback 保留，由 `ASR_PROVIDER` 环境变量切换。

## 最终决策

1. **三层降级链**：`glm_asr (PPIO) → whisperx (本地) → uniform_chunks (兜底)`，由 `app.config.Settings.asr_provider` 选首选层；任意层失败自动顺次降级，每个降级边界发 `severity="warning"` 的 VisionEvent。
2. **GLM-ASR 仅取文本，wav2vec2 forced alignment 单独跑**：`_glm_pipeline = ffmpeg.extract_audio → glm_asr.transcribe_glm → whisperx.align（接受外部文本，绕过 Whisper 转写）→ _segments_to_units`。该 align 输出与 WhisperX 全程跑一致的 segment 形态，下游单一切分器无需双路。
3. **Unit 切分逻辑重写**（`_segments_to_units`）：词级时间戳 → 四因素切分：词间 gap > `UNIT_GAP_SEC`（默认 0.15s）/ 累积字数 ≥ `UNIT_MAX_CHARS`（默认 12）/ 中文标点 `。？！，；` 高优先级断点；累积 < `UNIT_MIN_CHARS`（默认 4）拒绝软断（避免太碎），仅硬上限触发时强制断。
4. **PPIO endpoint 而非智谱原生**：`https://api.ppio.com/v3/glm-asr`，base64 上传 wav，复用 `LLM_API_KEY`。`asr_base_url` 字段允许未来切换到原生或其他代理；`model_asr=glm-asr-2512` 字段保留作未来切模型口子（PPIO 当前 endpoint 不读 model 字段）。
5. **transcript.json 跨阶段复用**：`recommend_templates_endpoint` 跑完 ASR 后写 `projects/{pid}/transcript.json`，`apply_short` 进 ASR 阶段前优先读盘，跳过重跑，发 `stage="2.pipeline.asr_reuse"` 事件标记复用。

## 已知代价

### 代价 1：GLM-ASR 30s 硬上限将阻塞 Phase 3 长视频

PPIO 与智谱 endpoint 文档均明确单次 ≤ 30s / 25MB。Phase 3（~3min 长口播）必须分块或换 ASR 后端。
**Followup**：暂不追踪 — Phase 3 整体规划尚未启动，分块 / 流式策略到时与 9-step 流水线一并设计；当前 Phase 2 短素材 ≤ 20s 完全在限内。

### 代价 2：wav2vec2 中文对齐模型首次拉取约 1.2 GB

首次跑 align 会从 HuggingFace Hub 拉 `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`，HF cache 已通过 `HF_CACHE_DIR` 重定向到 DATA_ROOT 内。
**Followup**：暂不追踪 — 一次性下载，且与现有 WhisperX 模型大小一个量级；dev 环境实测已 cached 在 `backend/data/.cache/huggingface/hub/`。

### 代价 3：PPIO 网络抖动 / 4xx 时全链路降级到本地 WhisperX，中文准确率回落

GLM 失败时自动 fallback 到 WhisperX，CER 从 ~7% 回到 ~12-15%，字幕同音字增多。降级路径走 `severity="warning"` VisionEvent 让工作台可见。
**Followup**：暂不追踪 — 三层降级是设计目标，准确率回落是接受代价；如长期降级（运行时观测），可由用户手动 `ASR_PROVIDER=whisperx` 强制走本地，或换代理。

### 代价 4：transcript.json 缓存与 normalized.mp4 一致性靠 project_id 隔离保证

重新上传素材会创建新 project_id，所以缓存不会 stale；但若以后允许同 project 内替换素材（如 Editor 加"重新上传"按钮），缓存需要 invalidate。
**Followup**：暂不追踪 — 当前 Phase 2 数据流不允许同 project 替换素材；若引入需在该流程中清理 transcript.json。
