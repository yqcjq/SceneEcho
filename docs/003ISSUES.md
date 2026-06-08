<!--
状态标签：[发现] / [讨论中] / [暂缓] / [进行中] / [已解决]
优先级标签：[P0 致命] / [P1 严重] / [P2 一般] / [P3 轻微]
类型标签：[崩溃] / [功能异常] / [性能] / [体验] / [安全] / [技术债]

新增条目追加到文件末尾，ISS 编号顺序递增，已解决条目不删除。
-->

## [ISS-001] gen-types.ts 产出的 zod const 未导出导致 frontend/renderer 构建失败

**状态**：[已解决]
**优先级**：[P0 致命]
**类型**：[崩溃]
**发现日期**：2026-06-06
**解决日期**：2026-06-06

**现象**：
`renderer/scripts/gen-types.ts` 与 `frontend/scripts/gen-types.ts` 调用 `jsonSchemaToZod(sub, { name: "${name}Schema", module: "none" })`。`module:"none"` 语义是"不输出 import/export，只返回裸表达式"，与 `name` 选项组合后 `name` 被忽略，生成内容形如 `z.object({...})`，下游 `export type X = z.infer<typeof XSchema>` 引用未声明符号 → tsc / vite build 立即报错 `Cannot find name 'XSchema'`。

**后果**：
`pnpm gen:types` 之后 `pnpm -F renderer typecheck` 与 `pnpm -F frontend build` 全部红，CI 全线阻塞，本地 `pnpm dev` 也无法启动 renderer/frontend。

**初步判断**：
已确认。读 json-schema-to-zod v2 选项语义后定位到 `module + name` 互斥的使用方式不正确。

**关联**：
-> renderer/scripts/gen-types.ts
-> frontend/scripts/gen-types.ts
-> decisions/（无，单点修复无方案分叉）
-> 004CHANGELOG.md [2026-06-06-1]

**解决方案**：
弃用 `name` 选项，仅用 `module:"none"` 取裸表达式，由生成脚本自行拼接 `export const ${name}Schema = ${expr};` + `export type ${name} = z.infer<typeof ${name}Schema>;`，确保 schema 与类型都导出且名字一致。

---

## [ISS-002] ffmpeg normalize filter 用表达式语法导致 Windows 下解析失败且 letterbox 逻辑错误

**状态**：[已解决]
**优先级**：[P0 致命]
**类型**：[崩溃]
**发现日期**：2026-06-06
**解决日期**：2026-06-06

**现象**：
`backend/app/render/ffmpeg.py::normalize` 的 `vf` 串使用 ffmpeg 表达式 `scale='if(gt(a,W/H),W,-2)':'if(gt(a,W/H),-2,H)'`。问题双重：
1. subprocess argv 直传时，单引号是字面量交给 ffmpeg 自己的解析器，Windows 上 filter graph 解析对内嵌 `,` 与 `'` 处理不稳，常报 `Error parsing filterchain`。
2. 表达式里 `W/H` 是整型字面量除法（`1080/1920 = 0`），`gt(a, 0)` 对几乎所有输入恒真 → scale 分支永远只走第一支，竖屏素材不会 letterbox。

**后果**：
任何 `POST /samples` 上传都会在 normalize 步骤抛 `CalledProcessError`，阶段 0 验证链路 1+3 完全无法跑通。

**初步判断**：
已确认。第一性原理：ffmpeg 早就为"按比例缩放并 letterbox 到固定画布"提供了组合惯用法 `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2`，无需手搓表达式。

**关联**：
-> backend/app/render/ffmpeg.py:normalize
-> 004CHANGELOG.md [2026-06-06-1]

**解决方案**：
重写 vf 为 `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2:color=black,fps=F`，完全避开表达式语法，跨平台稳定。

---

## [ISS-003] Remotion 渲染元数据在 selectComposition 之后被调用方覆盖，违反 v4 契约

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[功能异常]
**发现日期**：2026-06-06
**解决日期**：2026-06-06

**现象**：
`renderer/src/render.ts` 在 `selectComposition` 返回后做 `{...composition, width, height, fps, durationInFrames}` 拼出 `targetComposition` 再传给 `renderMedia`。Remotion v4 的 selectComposition 已经是 metadata 的固化点，调用方覆盖会绕过 `calculateMetadata` 钩子；且 `renderMedia` 内部还会用 serveUrl 重新解析 composition 元数据，自定义覆盖可能被忽略。

**后果**：
当 ProjectIR 的 canvas 与默认 1080×1920@30fps 不一致时，渲染出的 mp4 维度可能与 IR 声明不符；前端 `<video>` 显示与上传素材比例不匹配。

**初步判断**：
已确认。Remotion 官方对此场景的契约是 `<Composition>` 上声明 `calculateMetadata({props})` 推导元数据，selectComposition 自动触发它，调用方不应再二次覆盖。

**关联**：
-> renderer/src/render.ts:renderProjectIR
-> renderer/src/compositions/Root.tsx
-> renderer/src/compositions/projectMeta.ts（新增）
-> 004CHANGELOG.md [2026-06-06-1]

**解决方案**：
抽出 `compositions/projectMeta.ts` 共享元数据计算逻辑；`Root.tsx` 的 `<Composition>` 加 `calculateMetadata` 调用它；`render.ts` 移除 `targetComposition` 覆盖，直接把 `selectComposition` 的结果传给 `renderMedia`。

---

## [ISS-004] CLI ingest 在 ENABLE_CLI_INGEST=false 时静默退出 code 2

**状态**：[已解决]
**优先级**：[P3 轻微]
**类型**：[体验]
**发现日期**：2026-06-06
**解决日期**：2026-06-06

**现象**：
`backend/app/cli.py::_require_enabled` 在闸门未开时直接 `raise typer.Exit(code=2)`，没有任何 stderr 输出，开发者看到的现象是命令瞬退、无提示。

**后果**：
新人首次跑 `python -m app.cli ingest-sample ...` 完全摸不到头绪，需要翻代码才能发现是开关问题。

**初步判断**：
已确认。

**关联**：
-> backend/app/cli.py
-> 004CHANGELOG.md [2026-06-06-1]

**解决方案**：
在 raise 之前 `typer.echo("CLI ingest disabled. Set ENABLE_CLI_INGEST=true in .env to enable.", err=True)`。

---

## [ISS-005] Remotion 4.x 拒绝 file:// 资源导致渲染 demo 整链路失败

**状态**：[已解决]
**优先级**：[P0 致命]
**类型**：[崩溃]
**发现日期**：2026-06-06
**解决日期**：2026-06-06

**现象**：
`renderer/src/render.ts::renderProjectIR` 用 `pathToFileURL(userMaterialAbs).toString()` 把用户素材解析成 `file:///D:/Project/.../normalized.mp4` 喂给 `<OffthreadVideo>`。Remotion 4.0.473 在 Chromium 内的代理 endpoint 抛出 `SymbolicateableError: Can only download URLs starting with http:// or https://, got "file:///D:/..."`，`POST /render` 返回 500，`tasks_store` 把任务置为 `failed`。

**后果**：
任何 `POST /api/samples/{id}/render-demo` 都直接 failed，阶段 0 验证链路 1+3 完全无法跑通；前端只看到 backend 转发的 500 文本，无法定位真因。

**初步判断**：
已确认。本质是浏览器安全模型——Chromium 不允许页面脚本读 `file://` 资源（同源/文件系统访问限制），Remotion 渲染 = headless Chromium 截帧，asset 必须是 `http(s)` URL。Remotion 3.x 在 Node 端兜底支持过 `file://`，4.x 移除该兜底，回归浏览器原生行为。这不是 4.x 的"上线限制"，是浏览器本质，靠绕过 file:// 解决，不能靠"换更老的 Remotion"或"开 file:// 开关"。

**关联**：
-> renderer/src/render.ts:renderProjectIR
-> backend/app/main.py（已挂载 `/data` 静态路由，复用即可）
-> 004CHANGELOG.md [2026-06-06-2]

**解决方案**：
renderer 把 IR 里的 `user_material` 相对路径拼成 `{BACKEND_URL}/data/<rel>`（每段 `encodeURIComponent`）后作为 `inputProps.userMaterialUrl` 传入 `<OffthreadVideo>`；`BACKEND_URL` 通过 env 注入，本地默认 `http://localhost:18521`。后端早已在 `main.py` `app.mount("/data", StaticFiles(...))`，无新增依赖。


---

## [ISS-006] BGM stem 落盘路径与 events.jsonl 路径方案 B 不齐

**状态**：[发现]
**优先级**：[P3 轻微]
**类型**：[技术债]
**发现日期**：2026-06-08

**现象**：
`backend/app/extract/audio.py::_demucs_separate` 在 BGM 有人声且 `save_stem=true` 时把 stem 写到 `normalized_path.parent / "audio" / "bgm_stem.wav"`，对样例素材展开为 `samples/{sid}/audio/bgm_stem.wav`。Phase 0.5 已经把所有派生产物（events / frames / extracted）统一收到 `samples/{sid}/extracted/`（路径方案 B），audio stem 单独散在 `audio/` 子目录里。

**后果**：
不影响功能，但 1B 集成时 KB store 与 cleanup cron 需要为 `audio/` 多写一条扫描规则；用户从 SubcapabilityLab `audio` 跑完 → 工作台第三栏 IR 树字段填充时若想链到 stem 文件，路径不在派生产物 root 下不直观。

**初步判断**：
已确认。Phase 1A 的优先级是子能力本身能跑通且 fallback 完整；目录归位作为 1B 集成期的小整理项。

**关联**：
-> backend/app/extract/audio.py:_demucs_separate
-> docs/001ARCHITECTURE.md（约定 D10）

---

## [ISS-007] Phase 1A 二核：prompt 转义错位 + IR 写入伪装 TemplateIR + lab runner 重复样板

**状态**：[已解决]
**优先级**：[P0 致命]
**类型**：[功能异常]
**发现日期**：2026-06-08
**解决日期**：2026-06-08

**现象**：
Phase 1A 第一版交付（[2026-06-08-2]）二次核查发现以下问题，按 LLM 调用链 / IR 写入 / 子能力编排三类聚合：

1. **prompt 模板字面 `{{` `}}`**：`backend/app/llm/prompts/1a_*.md` 共 7 个文件用 `{{` `}}` 双花括号转义（`str.format` 风格），但所有调用点统一走 `load_prompt(name)`（裸读），LLM 收到的 system prompt 含字面 `{{` `}}` 字符。
2. **`_RETRY_DELAYS = (0.5, 2.0, 6.0)` 死代码**：`backend/app/llm/client.py::_invoke` 循环只在 `attempt < len(_RETRY_DELAYS) - 1` 时 `await asyncio.sleep(delay)`，最后一个 6.0 永远不执行。
3. **`_attach_frames_anthropic` 缺帧静默**：本地文件不存在时 `log.warning + continue`，调用照常发出（无图）。
4. **VLM `frames_appeared` 索引语义模糊**：`captions.py` / `stickers.py` 的 user prompt 没声明 0-indexed 还是 1-indexed，VLM 给 1-indexed 时 `limited[i]` 越界被 `_merge_captions` 丢弃。
5. **调用级事件硬塞 `ir_target=IRTarget(path="skeleton")`**：`captions.py:142,153` 与 `stickers.py:89` 把整个 `parsed.model_dump()` 写入 `TemplateIR.skeleton`（应为 `list[Slot]`），前端 lodash.set 直接覆盖根字段类型。
6. **硬编码 `skeleton[0]` 路径**：`captions_anim.py:75` 与 `stickers.py:225` 注释「caller rebinds to actual slot index」但 `lab.py` runner 没 rebind，多 caption / 多 sticker 时全部互相覆盖。
7. **`_refine_with_histogram` 命名漏 CI 守卫**：`scripts/check_parent_event_id.py` 用 `endswith("_refine")` 匹配，函数名以 `_histogram` 结尾被漏掉；同期 `classify_caption_function` 等"前缀 classify_"命名也不在匹配范围。
8. **PLAN 与实现的宏观矛盾**：PLAN.md 1361 行声明"本阶段不产出 TemplateIR"，但 11 个子能力 VisionEvent 全部用 `ir_type="TemplateIR"` + `path="skeleton[N].xxx"` / `"global_style.audio"`，前端 lodash.set 把它们拼成"半成品 TemplateIR"显示在右栏。
9. **`lab.py` 7 个 `_run_*` 重复**：每个 runner 90% 代码相同（`detect_scenes → sample_frames → 该子能力`），多 fixture × 多 subcap 时 detect/sample 反复执行。

**后果**：
- 1～4 让真实 VLM 路径几乎全部回退到 stub（CI 单测因 `no_credentials` fixture 强制 fallback 路径，拦不到）；接入真实 key 后整个 1A 视觉子能力实际产出与人工标注无关的默认 schema。
- 5～7 让前端 IR 树展示错位：调用级事件覆盖 `skeleton` 根字段，多 caption 全打到 slot 0 互相覆盖，CI 漏报让"必传 parent_event_id"约束在 `_refine_with_histogram` 与 `classify_caption_function` 等命名上失效。
- 8 在工作台右栏渲染了一棵假 `TemplateIR`，1B 集成期 `skeleton.py` 试图读这棵树写真 TemplateIR 时类型不匹配。
- 9 让 11 个子能力跑同一 fixture 时 detect/sample 跑 11 次，浪费时间且 lab runner 无法被未来 1B pipeline 复用。

**初步判断**：
已确认。第一性原理：1A 阶段输出的本就是"识别报告"而非 TemplateIR；prompt 模板转义需统一为单一规则（裸 `{` `}` 或全量走 `render_prompt`）；子能力编排需要共享上下文对象避免每个 runner 重复样板。

**方案讨论**（已确认）：
- prompt 转义：选裸 `{` `}`（无 substitution 时不该走 `str.format`），保留 `render_prompt` 供未来动态拼装。
- IR 写入：新增 `Phase1AReport`（`backend/app/ir/phase1a_report.py`），所有 1A 子能力的 ir_target 切到这棵树；`IRTarget.ir_type` Literal 加 `"Phase1AReport"`；前端 IR 面板按最近事件 ir_type 动态显示标题。
- 子能力编排：新增 `Phase1AContext`（`backend/app/extract/context.py`）lazy 缓存 scenes/frames/client；子能力签名收口为 `detect_X(ctx, *, parent_event_id=None)`；lab runner 简化到 `await sub.runner(ctx)`。
- integration tests：本期只补 mock-level（`tests/integration/test_subcap_shapes.py` 用 seeded ctx 跑全部 subcap 断言事件结构 + Phase1AReport schema round-trip）；F1 / IoU 指标基线留待用户准备完整 fixtures 后续补到 `test_subcap_baselines.py`。

**关联**：
-> backend/app/llm/client.py（_RETRY_DELAYS / _attach_frames_anthropic / _invoke 循环）
-> backend/app/llm/prompts/1a_*.md × 7（{{ }} → { }）
-> backend/app/ir/phase1a_report.py（新增）
-> backend/app/ir/vision_event.py（IRTarget.ir_type Literal 扩 Phase1AReport）
-> backend/app/extract/context.py（新增 Phase1AContext）
-> backend/app/extract/{scenes,captions,captions_anim,stickers,motion,transitions,masks,color,audio}.py
-> backend/app/understand/vision.py
-> backend/app/api/lab.py
-> scripts/check_parent_event_id.py（前后缀双匹配）
-> backend/tests/integration/test_subcap_shapes.py（新增）
-> frontend/src/types/workbench.ts、frontend/src/components/workbench/WorkbenchIRPane.tsx
-> docs/001ARCHITECTURE.md（D17 / D18）
-> docs/002STRUCTURE.md
-> 004CHANGELOG.md [2026-06-08-3]

**解决方案**：
新增 `Phase1AReport` IR + `Phase1AContext` 共享上下文，11 个子能力签名统一 `(ctx, *, parent_event_id)`，所有 ir_target 切到 Phase1AReport（列表型 op=append、字典型 path=`zoom_directions.<idx>`、单值型整对象 / 子字段写入）；prompt 模板 `{{` `}}` → `{` `}`；`_RETRY_DELAYS` 改 `(0.5, 2.0)` 并把循环改为 `len+1` 次尝试；`_attach_frames_anthropic` 缺帧 `raise ValueError` 走 retry/fallback 链；`captions_anim` / `caption_function` 加 `caption_idx` 形参索引到 `Phase1AReport.captions[N]`；`stickers refine` 加 `sticker_idx`；`_refine_with_histogram` 改名 `_color_histogram_refine`；`check_parent_event_id.py` 加前缀匹配 `refine_` / `phase2_` / `classify_`；前端 `IRTargetType` 加 `Phase1AReport`、`WorkbenchIRPane` 标题动态显示 ir_type；新增 9 条 mock-level integration tests 覆盖 11 子能力的事件结构 + ir_target + schema 合法性。

---

## [ISS-008] Phase 1A 工作台可视化盲点：实体事件缺 frame_url + IR 信息缺 reasoning + mask 单帧 VLM 不稳

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[功能异常]
**发现日期**：2026-06-08
**解决日期**：2026-06-08

**现象**：
用户在 lab UI 用真实 LLM key 跑 captions / stickers / masks 子能力时反馈：

1. **左栏既看不到帧也看不到框**：`captions.detect_captions` / `stickers.detect_stickers` 等子能力发出的实体级 `VisionEvent` 只填了 `bbox_norm`，**没填 `frame_url`**；前端 `WorkbenchVisionPane` 在 `event.bbox_norm && hasFrame && frameSize` 三个条件齐全时才渲染 `BboxOverlay`，缺 frame_url 直接退到「no frame」占位，bbox 无处可叠 → 用户感受到「点开事件什么都看不见」。grep `extract/*.py` 全文 `frame_url=` 0 命中，确认问题。
2. **右栏 IR 信息密度比 [2026-06-08-2] 上一版变浅**：[2026-06-08-3] 二核重构后调用级事件 `ir_target=None`、实体级事件写精简过的 `Phase1ACaptionEvent`，砍掉了 `reasoning` 与 raw VLM 字段（`color_hex` / `anim_in_type` / `layout`），导致用户在右栏只看到「采集了几条字幕」但没有具体内容。
3. **画面字幕 vs 语音字幕命名歧义**：1A.captions prompt 标题用「字幕」二字，没声明只识别画面里烧入的视觉字幕；用户搞不清识别的是语音转写还是画面文字。
4. **mask 检测不稳定**：`detect_masks` 每个 scene 只取**中点一帧**送 VLM，蒙版只在 scene 部分时间出现 / 中点恰好没蒙版就漏报；用户反馈贴纸 / 切点的稳定性远高于 mask。

**后果**：
- 1 让 Phase 0.5 阶段能用的 bbox 可视化在 Phase 1A 真实跑时完全失效，工作台变成「数字面板 + 文字日志」而不是「AI 看到什么」的可视化。
- 2 让 Phase 0.5 → 1A 的体验回退（用户原话「右栏会非常模糊笼统，没有具体内容」），降低人工核验信心。
- 3 在产品定义层让用户怀疑功能定位（"它到底在识别啥"）；接 ASR 之后会进一步混淆。
- 4 让 mask 在 fixture 测试中表现不可预测，明明蒙版存在却报无 — 而几何 mask 本身适合 CV（HoughCircles / Canny / HoughLines）确定性检测，不依赖 VLM 截帧运气。

**初步判断**：
已确认。第一性原理：实体事件携带「entity 出现的那一帧 url」是 BboxOverlay 工作的前提；Phase1AReport 作为「识别报告」IR 应保留 VLM 的 reasoning + raw 字段供审计；几何 mask 在视觉特征足够清晰时 CV 比 VLM 更适合（确定性 + 多帧稳定）。

**关联**：
-> backend/app/extract/captions.py（entity_ev 补 frame_url + Phase1ACaptionEvent 补 reasoning / color_hex_raw / anim_in_type_raw / layout_raw）
-> backend/app/extract/stickers.py（entity / refine ev 补 frame_url + detection 补 reasoning）
-> backend/app/extract/captions_anim.py（verify_caption_anim 加 anchor_frame_url 形参）
-> backend/app/extract/masks.py（重写 — CV 主路径多帧投票 + VLM 兜底）
-> backend/app/understand/vision.py（classify_caption_function 给事件挂 caption.bbox + 修正 ir_value）
-> backend/app/api/lab.py（_run_captions_anim 解析 anchor_frame_url 透传）
-> backend/app/llm/prompts/1a_captions.md（标题 + 边界声明改「画面字幕」）
-> backend/app/ir/phase1a_report.py（Phase1ACaptionEvent / Phase1AStickerDetection 补 reasoning + raw 字段 + docstring 声明画面字幕）
-> 004CHANGELOG.md [2026-06-08-4]

**解决方案**：
- 实体级事件全部补 `frame_url`，源帧选 entity `frames_appeared` 列表的第一帧，从 `Phase1AContext.frames()` 缓存里拿 `rel_path` 拼 `/data/<rel>`。
- `Phase1ACaptionEvent` 补 `reasoning` / `color_hex_raw` / `anim_in_type_raw` / `layout_raw` 字段；`Phase1AStickerDetection` 补 `reasoning` 字段；entity_ev 写 ir_value 时一并带上。
- 1a_captions.md 标题改「画面字幕样式与位置识别」，开头加一段强调「不处理语音」「不识别原文」「只看画面里烧入的视觉文字」；`Phase1ACaptionEvent` docstring 同步声明。
- `detect_masks` 重写：scene 内首/中/末三帧 OpenCV `HoughCircles` / Canny 矩形 / `HoughLinesP` 三类检测多数决；`majority_vote` 至少 quorum=ceil(n/2) 同 kind 才确认；CV 全 False 时 VLM 兜底（一次性看三帧）；CV 候选 + 最终判定都发事件带 frame_url。

---

## [ISS-009] Phase 1A 工作台首屏截帧需刷新才显示

**状态**：[已解决]
**优先级**：[P2 一般]
**类型**：[体验]
**发现日期**：2026-06-08
**解决日期**：2026-06-08

**现象**：
ISS-008 修复后实体事件已带 frame_url 与 bbox，但首次进入 `/workbench/{taskId}` 时左栏长时间空白（数秒），手动刷新一次后立即显示。复现路径：lab UI 跑完一个 subcap → 跳转 workbench → 等。

**后果**：
人工核验体验"识别完成但要等很久 / 刷新一次才能看图"，影响快速迭代。

**初步判断**：
已确认。SSE replay 在订阅瞬间一次性涌入历史事件，`autoFollow=true` 让每条新事件都成为 `selectedEventId` → `WorkbenchVisionPane` 的 `<img src={frame_url}>` 在事件涌入期间反复改 src → 浏览器对前一个 src 的 in-flight HTTP 请求持续被取消和重发，只有"最后一条事件"对应的 img 真正完成加载。刷新页面时事件已经在 jsonl 里，replay 是同步快速跑完，最后一次 src 落定后 img 加载顺利完成 → 用户感受"刷新就有了"。

**关联**：
-> frontend/src/state/workbench.ts（appendEvent 时 preloadFrame 后台拉图入 HTTP cache）
-> frontend/src/components/workbench/WorkbenchVisionPane.tsx（loading / error 占位 + decoding=async + loading=eager）
-> 004CHANGELOG.md [2026-06-08-5]

**解决方案**：
- store `appendEvent` 时即调 `new Image(); img.decoding="async"; img.src = event.frame_url`，每条事件一进 store 就在后台拉图入浏览器 HTTP cache；后续 `<img>` 元素的 src 任意切换都从 cache 即时出，不再受 SSE 涌入抖动影响。
- `<img>` 加 `decoding="async"` + `loading="eager"`，解码不阻塞主线程。
- `WorkbenchVisionPane` 在 `hasFrame && !frameSize && !frameError` 时显示 "loading frame…" 脉冲占位（事件 frame_ts 同显），加载失败时显示明确错误 + url 便于排查。
