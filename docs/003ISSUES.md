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

---

## [ISS-010] Phase 1B 二核：StyleRule.audio 虚位 + degraded 路径混命名空间 + 多处冗余/打补丁

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[技术债]
**发现日期**：2026-06-09
**解决日期**：2026-06-09

**现象**：
Phase 1B 第一版交付（[2026-06-09-1]）二次核查发现以下问题，按 IR 设计 / pipeline 编排 / 数据库初始化 / UI 完整性四类聚合：

1. **`StyleRule.audio` 是没有真消费者的 per-slot 虚位**：1A `extract_bgm` 只产出一个全局 `AudioStyle`（口播视频通常一首 BGM），`extract/skeleton.py:225` 把同一对象 `audio=report.audio or AudioStyle()` 复制到每个 slot 的 `StyleRule.audio`，下游 `kb/tagging.py:62` 又只读 `slot[0].style.audio`——per-slot 字段是个没有真消费者的占位，并且 slot[0] 硬编码恰是 [ISS-007] 第 6 项已声明禁止的反模式。

2. **`TemplateIR.degraded` 的键混了两套命名空间**：`extract/pipeline.py::_safe(label, field_key, ...)` 直接把 `field_key` 写入 `ir.degraded`，但调用点喂的 field_key 一半是 TemplateIR 路径（`skeleton` / `tags` / `sanity_check` / `duration`），一半是 Phase1AReport 路径（`captions` / `zoom_curves.0` / `captions.3.verified_anim_in` / `transitions` / `masks`）。`TemplateIR.degraded` 字段挂在 TemplateIR 上，但其内容里有 Phase1AReport 命名的键——UI banner 没法据此跳转到真实 IR 字段。

3. **`pipeline.py` 通过 `ctx._frames` 私有属性回收帧**：`extract_template` stage 3 处 `frames_for_summary = ctx._frames or []` 绕过 `Phase1AContext.frames()` 公共 lazy 入口。私有属性被外部依赖会让未来 ctx 改 cache 实现时静默挂掉。

4. **`pipeline.py::_color_to_report` 与 `extract/color.py::_to_color_report` 完全重复**：两份 8 行代码做完全相同的字段映射（`ColorStyleResult` → `Phase1AColorReport`），违反复用原则。

5. **`kb/store.py` 每个 CRUD 入口都调 `init_db()`**：6 个 CRUD 函数（save/get/list/delete/update_tags/update_caption_placeholder）每次入口都跑 DDL；`main.py` 的 lifespan 已经调过一次，per-call 调用是冗余且与 `tasks_store` 约定不一致。

6. **`kb/sanity.py:66` 的 `ir.model_dump_json()[:2000]` 中段截断**：长模板（多 slot + 多字幕）在 2000 字符处被切断，VLM 收到的是半 JSON 半乱码——审计员把不完整的模板当作完整模板审计。

7. **`extract/pipeline.py` 中 `masks=masks` 直接用 `dict[int, ...]` 写入 `Phase1AReport.masks: dict[str, ...]`**：pydantic strict 模式下报 `Input should be a valid string`；同期 zoom_directions / transitions 都已用 `{str(k): v for k, v in ...}` 显式转 key，masks 漏了。集成测试一跑即崩。

8. **TemplateLibrary.tsx 的 `patchTemplateTags` import 是死引用**：UI 里没有 tags 编辑入口，但后端 `PATCH /templates/{id}/tags` 端点已实现且 PLAN 1538 隐含"模板可手工改 tags"。

9. **`scripts/check_parent_event_id.py` 误判 `_classify_role`**：skeleton.py 里的纯阈值映射函数（`start_ratio` → `开头 / 主体 / 结尾`）名字以 `_classify` 结尾被 CI 守卫识别为"phase-2 VLM 调用"，要求传 `parent_event_id=`——但它根本不发事件。守卫的语义边界是"AI 调用链的子步骤"，不是"任何叫 classify 的函数"。

**后果**：
- 1 + 2 让 1B 的 IR 设计在第一版就含两处「假约束」：per-slot audio 字段误导未来 Phase 2 的 apply 层（让人以为可以 per-slot 改 BGM），degraded 命名空间混乱让"模板有 N 项 degraded"这个 UI 提示无法引导用户去看具体字段。
- 3 是一颗定时炸弹：未来 Phase1AContext 改 lazy cache 实现（比如改成 `cached_property` 或 LRU dict）时，pipeline.py 的私有访问静默挂掉。
- 4 + 5 + 6 + 7 是经典"在原有逻辑上打补丁"的现场——color 转换两份、init_db 散在每个 CRUD、sanity 用字符串切片当结构降维、dict key 类型在三处的 str(k) 转换中漏一处。
- 7 单点让 1B 集成测试当前直接失败（未跑 `pytest tests/integration/test_extract_1b.py`，已在 二核 中复现）。
- 8 + 9 是 UI / CI 完整性问题：tags 编辑器没接入、CI 守卫边界过宽。

**初步判断**：
已确认。第一性原理：
- 全局信号（音频 / 调色）应该挂在 IR 顶层，而不是被复制到每个 slot；StyleRule 的语义是"这一段 slot 的剪辑配方"，全局事物不属于这里。
- `degraded` 字段属于 TemplateIR，键的命名空间也应该是 TemplateIR——pipeline 层是 1A 的消费者，理应在那里完成 1A 路径 → TemplateIR 路径的翻译。
- 公共 lazy 接口存在的意义就是给跨模块访问用，私有属性应当被守住。
- 重复代码、散落的 init_db、字符串截断、漏掉的 str(k)——都是同一类"在第一版里偷懒"的产物，二核就是用来偿还这笔债的。

**方案讨论**（已确认）：
- IR 改造：`TemplateIR` 新增顶层 `audio: AudioStyle | None`；`StyleRule.audio` 删除。skeleton.py 不再 per-slot 填 audio，pipeline.py 用 `ir.audio = report.audio` 直接装配。tagging.py 从 `ir.audio` 读取。
- degraded 命名空间统一：pipeline.py 顶部加 `SUBCAP_TO_IR_PATH` 表（subcap label → TemplateIR 路径）+ `_ir_path_for(field_key)` 翻译函数；`_safe` 在写入 `ir.degraded` 前一律走翻译。Phase1AReport 路径（如 `zoom_curves.3` / `captions.5.verified_anim_in`）按"剥后缀 → 折叠"两步规则映射到 `skeleton.*.style.visual.zoom_keyframes` / `skeleton.*.style.caption`。
- 工具函数复用：`extract/color.py::_to_color_report` 改名 `to_color_report`（去下划线公开），pipeline.py 直接 import 使用，删除重复定义。
- 数据库初始化：`kb/store.py` 所有 CRUD 移除 per-call `init_db()`；约定 lifespan 是唯一调用方；`tests/conftest.py::task_with_events` fixture 同步加 `kb_store.init_db()` 镜像 lifespan。
- sanity 审计 prompt：新增 `_summarize_for_audit(ir)` 显式构造 bounded 摘要（每 slot 一行，关键字段全留），替代 `model_dump_json()[:2000]`。
- masks dict key：`pipeline.py` 收口处加 `{str(k): v for k, v in masks.items()}` 与 zoom_directions / transitions 对齐。
- pipeline 私有访问：`frames_for_summary = ctx._frames or []` 改为 `try/except await ctx.frames()` 走公共入口。
- TemplateLibrary tags 编辑器：在详情页 `<TagsEditor>` 子组件，4 个 input 对应 position / function / scene / notes，dirty-state 控制保存按钮禁用，调 `patchTemplateTags`。
- CI 守卫：`_classify_role` 改名 `_role_for_position`——名字本身就更准（按位置阈值映射，不是语义分类），同时绕过 CI 误判，不动 CI 守卫边界。

**关联**：
-> backend/app/ir/template.py（TemplateIR.audio 顶层 / StyleRule.audio 删）
-> backend/app/extract/pipeline.py（SUBCAP_TO_IR_PATH 表 + _ir_path_for + masks str-key + ctx.frames() 公共入口 + 复用 to_color_report）
-> backend/app/extract/skeleton.py（移除 audio per-slot 装配 + _classify_role → _role_for_position）
-> backend/app/extract/color.py（_to_color_report → to_color_report 公开）
-> backend/app/kb/store.py（移除 6 处 per-call init_db）
-> backend/app/kb/tagging.py（slot[0].style.audio → ir.audio）
-> backend/app/kb/sanity.py（_summarize_for_audit 替代字符串截断）
-> backend/app/llm/prompts/scenarios/full_extract_demo.json（global_style.audio → audio 路径同步）
-> backend/tests/conftest.py（task_with_events fixture 镜像 lifespan 调 kb_store.init_db）
-> backend/tests/unit/test_skeleton.py（_classify_role 重命名同步）
-> frontend/src/pages/TemplateLibrary.tsx（新增 TagsEditor 子组件）
-> shared/ir.schema.json（gen_schema 重生成）
-> renderer/src/types/ir.ts、frontend/src/types/ir.ts（pnpm gen:types 重生成）
-> docs/001ARCHITECTURE.md（D24 新增 + D17 微调）
-> docs/002STRUCTURE.md（无新增文件，annotation 微调）
-> 004CHANGELOG.md [2026-06-09-2]

**解决方案**：
将全局音频升到 `TemplateIR.audio`，删除 `StyleRule.audio`；引入 `SUBCAP_TO_IR_PATH` 把 1A subcap field_key 翻译为 TemplateIR 路径后再写 `ir.degraded`；`extract/color.py::to_color_report` 公开复用、`pipeline.py` 删除重复定义；`kb/store.py` 移除 per-call `init_db()`、`conftest.py` 镜像 lifespan 补 fixture；`kb/sanity.py` 用结构化 `_summarize_for_audit` 替代字符串截断；pipeline.py masks 也走 `{str(k): v}`；私有 `ctx._frames` 改公共 `await ctx.frames()`；TemplateLibrary 详情页加 `<TagsEditor>` 接通后端 PATCH /tags；`_classify_role` 改名 `_role_for_position` 绕过 CI 守卫误判。`pnpm gen:types` 同步两端 zod；80/80 backend 测试 + 11/11 frontend 测试 + renderer/frontend typecheck 全绿。


---

## [ISS-011] Phase 1B 工作台体感反馈 — 原视频缺位 / VLM 卡片乱序 / Reasoning 截断

**状态**：[已解决]
**优先级**：[P2 一般]
**类型**：[体验]
**发现日期**：2026-06-09
**解决日期**：2026-06-09
**解决方案**：右栏增 frame/video toggle（后端 `/api/tasks/{id}` 补 `normalized_media_url`，前端按需挂载 `<video controls>`，`autoFollow=false` 时按选中事件 `frame_ts` 命令式 seek，autoFollow 时不打断连续观看）；中栏默认按 `stage` 分组（`groupByStage` 按 first sequence 排，组内沿用到达顺序），保留按到达顺序视图作可切；中栏 reasoning 改 `whitespace-pre-wrap` 自然多行（卡片本来就完整显示，移除原误加的 toggle）；右栏 IRPane 底部加 inline detail strip——点击叶子节点 pin 路径，`lodash.get(ir, path)` 实时取值显示全文（流式写入同步刷新），string 直显 / object 走 JSON stringify。

**现象**：
Phase 1B 成品试用（在 `/sample-extract` 上传 10s+ 视频触发提取并进入 `/workbench/{task_id}`）暴露三处工作台体感缺陷，本质同源——三栏页面对"AI 决策可视化"做得彻底，但对"决策与原素材 / 视频时间 / 推理全文"的锚定全部缺位。打包为一条 issue 一次性收口：

1. **右栏 `WorkbenchVisionPane` 无原视频回看入口**：左栏只显示选中事件对应的单帧截图（`frame_url`），整段原视频在工作台范围内完全不可访问。用户在中栏读 VLM 卡片时无法回放原视频确认"AI 现在描述的是视频里的哪一段"，长视频甚至会让用户怀疑"我刚才到底传了哪个文件"。

2. **中栏 `WorkbenchEventStream` 按事件到达顺序排，并发场景下严重乱序**：`extract_template` 多子能力（captions / stickers / zoom / transitions / masks / color / audio）`asyncio.gather` 并发跑，VLM 单次延迟 2–10s。中栏按事件 push 到 store 的顺序追加渲染——视频长度 ≥ 10s 时，用户看到的卡片排列与原视频时间顺序完全不一致（8s 字幕 → 2s 贴纸 → 6s zoom 跳来跳去），无法按"视频从头到尾发生了什么"的心智模型理解 AI 决策。

3. **右栏 `WorkbenchIRPane` Reasoning 字段被省略号截断**：VLM 返回的 `reasoning` 经常 100+ 字中文推理，遇到 CSS `text-overflow: ellipsis` 被截断为单行 + `…`；既不支持换行、也不支持横向滚动、也不支持点击展开。用户能看到"AI 决定了什么"但看不到"AI 为什么这么决定"，与产品定位（可解释性）直接冲突。

**后果**：
工作台的可解释性叙事缺多处关键锚点——决策锚不回原始素材（1）、锚不回视频时间顺序（2）、锚不到完整推理（3）。三处叠加后，用户对中栏卡片的判断完全脱离原始上下文，工作台从"白盒"退化为"半盒"。

**初步判断**：
已确认。三处均为前端展示层缺陷，与后端事件流 / IR 设计无关：
- 第 1 项纯属漏做："AI 决策可视化"设计聚焦三栏抽象，未把"原素材回看"列入需求。
- 第 2 项属设计耦合："传输模型 ≠ 展示模型"未做区分——SSE 按到达顺序广播是物理事实，但展示层不应继承。
- 第 3 项纯样式 bug，单点修复。

修复方向已与用户对齐：
- **第 1 项**：右栏 `WorkbenchVisionPane` 顶部加一个 toggle 按钮，开启后**把当前的单帧截图区域替换为 `<video src={normalized_mp4_url} controls>`**（位置不变、与帧同位复用，不另开浮层 / 不另占栏位）。视频源走 `samples/{sid}/normalized.mp4` 或 `projects/{pid}/normalized.mp4` 静态路径，按 task 的 `resource_kind / resource_id` 反查；`/data/*` 静态路由已存在可直接拼。
- **第 2 项**：中栏改"按 `stage` 分组的折叠区"为默认视图（caption_style / caption_anim / sticker / zoom / transition / mask / color / tag / sanity / asr / dedup / segment / ...），组内按到达顺序追加；保留"按到达顺序"视图为可切换备选给调试用户。组内按 `media_ts` 升序排序的能力依赖 PLAN v3.3 Phase 2.6 才补的 `VisionEvent.media_ts` 字段——本 issue 不强依赖，先按 stage 分组也可独立交付；待 `media_ts` 字段补齐后再开第二轮升级组内排序。
- **第 3 项**：reasoning 区域改 `white-space: pre-wrap` + 默认折叠 3 行（`-webkit-line-clamp: 3` 或 max-height 计算）+ 右下角 "展开全文 / 收起" 按钮；展开后纵向自然撑开。不引入浮层，保持卡片内布局连贯。

**关联**：
-> frontend/src/components/workbench/WorkbenchVisionPane.tsx（顶部 video/frame toggle + 视频/帧切换渲染 + autoFollow 守卫）
-> frontend/src/components/workbench/WorkbenchEventStream.tsx（新增 group_by_stage 默认视图 + 视图模式切换 + reasoning pre-wrap 自然多行）
-> frontend/src/components/workbench/WorkbenchIRPane.tsx（叶子点击 pin 路径 + 底部 detail strip + lodash.get 实时取值）
-> frontend/src/state/workbench.ts（新增 visionPaneMode / streamViewMode 两个 UI 态）
-> backend/app/api/tasks.py（GET /tasks/{id} 补 normalized_media_url 字段；按 resource_kind 表翻译 /data/* 路径，文件不存在则返 null）
-> frontend/src/api/index.ts（TaskStatus 接口补 resource_kind / resource_id / normalized_media_url）
-> frontend/src/pages/Workbench.tsx（透传 normalized_media_url 到 WorkbenchVisionPane）
-> docs/decisions/（无，单点 UI 修复无方案分叉）
-> 004CHANGELOG.md [2026-06-09-4]



---

## [ISS-012] Phase 2 ★MVP 闭环 — short 口播 + KB 模板 → 自动出片

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[功能异常]
**发现日期**：2026-06-09
**解决日期**：2026-06-09

**现象**：
PLAN.md 1570-1666 行声明阶段 2 ★MVP 闭环：用户传 10–20s 一镜到底口播短素材 + 从 KB 指定一个模板 → ASR 对齐 → 映射到模板骨架 → 套字幕风格（含多行 + placeholder 引导）+ 缩放 + BGM（features 或 original）+ 贴纸（占位）→ 渲染 MP4 返回；推荐 + apply 全过程在工作台可见。落地前 Phase 0 / 0.5 / 1A / 1B 已完成，但 backend 没有 `apply/` 包、没有 ASR / 推荐 / 缺口补全 / 字幕填充 / BGM 选曲 / 渲染端缺多 segment 支持，前端没有 Editor 页面。

**后果**：
不开 Phase 2 就没有"出片"产品形态——KB 里只有模板没有产物，AI 工作台只看得到 extract 链路看不到 apply 链路，整个项目停在"识别得到但用不到"的尴尬位置。

**初步判断**：
已确认。Phase 2 是项目第一个端到端有产物的阶段，必须完整落地。设计沿用 1B 的 `_safe(label, ir_path, coro)` 降级范式，新增 `apply/` 包与 1B 的 `extract/` 包对称。

**关联**：
-> backend/app/ir/project.py（ProjectIR.degraded 字段）
-> backend/app/understand/asr.py（WhisperX lazy import + 等距 fallback）
-> backend/app/kb/recommend.py（VLM 模板推荐 top-k）
-> backend/app/apply/{__init__,mapping,gaps,fill,style,pipeline}.py（apply DAG）
-> backend/app/render/ffmpeg.py（mix_bgm + extract_audio + compose_segments）
-> backend/app/api/projects.py（recommend / apply / render / preview-props / mix-bgm 端点）
-> backend/app/llm/prompts/{2_recommend,2_caption_emphasis,2_fill_gap}.md
-> renderer/src/compositions/{Project,Caption,ZoomLayer,Sticker}.tsx + preflight.ts
-> frontend/src/{api/index.ts,components/RemotionPlayer.tsx,pages/Editor.tsx,main.tsx}
-> backend/tests/{integration/test_apply_phase2,unit/test_apply}.py
-> 004CHANGELOG.md [2026-06-09-5]

**解决方案**：
按 PLAN 完整落地阶段 2：新增 `apply/` 包 6 文件（mapping / gaps / fill / style / pipeline + __init__）；新增 `understand/asr.py`、`kb/recommend.py` 各 1 文件；扩 `render/ffmpeg.py`（mix_bgm + extract_audio + compose_segments 三函数）；扩 `api/projects.py` 五端点（recommend / apply / get / preview-props / render / mix-bgm）；renderer Project.tsx 重写为多 Sequence 多 ZoomLayer 多 Sticker per-segment；新增 ZoomLayer.tsx / Sticker.tsx / preflight.ts；renderer Caption.tsx 加 emphasis_words 子串高亮；新增 prompts 三份（2_recommend / 2_caption_emphasis / 2_fill_gap）；前端新增 `/editor` 页 + `RemotionPlayer` CSS-based 预览组件 + `/api` 客户端方法；ProjectIR 加 `degraded` 字段与 TemplateIR 对称；新增集成 + 单元测试覆盖 PLAN 验证 2 / 3 / 4 / 5 / 11。Caption.text === Unit.text 严守 D11；fill 段速度让 output_span = slot.nominal 保持 timeline 连续；ASR 缺包走 fallback 不阻塞 pipeline；BGM 走 BGM_STRATEGY 双策略；RemotionPlayer 选 CSS-based 而非打包 Remotion bundle 进 frontend——避免组件源双份维护（PLAN 1644-1649 设计意图同样可达）。

---

## [ISS-013] Phase 2 二核：timeline 漂移 / Sticker 坐标系混淆 / BGM ducking 未接入 + 多处冗余

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[功能异常]
**发现日期**：2026-06-09
**解决日期**：2026-06-09

**现象**：
对 ISS-012 落地的阶段 2 ★MVP 闭环做二核，发现三个第一性原理层面的不一致 + 一组 P2 冗余/打补丁：

1. **Timeline 漂移**：`apply/mapping.py` 累积 `timeline_cursor` 时用了 `output_span = max(slot.min, min(slot.max, src_span/speed))` 的 banding 值；`PlacedSegment` 仅持久化 `src_timerange + speed`，渲染端 (`projectMeta.ts` / `Project.tsx` / `RemotionPlayer.tsx`) 一律用 `(end-start)/speed` 推算 output_span，**不感知 banding**。复现：用户素材 15s + 模板 voice nominal 10s（1.5×长）→ Slot 0 mapping cursor 前进 banded 3.0s 但渲染端实际播 5/1.2 ≈ 4.17s，第二段在 [3.0, 4.17] 与第一段重叠。
2. **Sticker 坐标系混淆**：`extract/skeleton.py:_stickers_in` 把 `Phase1AStickerDetection.sticker.start/end`（**样例视频绝对秒**）原样拷贝到 `Slot.style.stickers`；renderer `Project.tsx:122` 写 `stk.start - seg.timeline_start`，前者是模板坐标系、后者是 ProjectIR 坐标系，两个坐标系直接相减结果无意义，贴纸在最终 MP4 上出现的时刻是错的。
3. **BGM ducking 未接入主流程**：`render/ffmpeg.py:mix_bgm` 实现完整、`/projects/{id}/mix-bgm` 是 dev hook，但 `apply/pipeline.py` 选完 `bgm_track` 后**从不主动跑 mix_bgm**，renderer 端 `<Audio src={bgmUrl}/>` 直接播原始 BGM，违反 PLAN 1611 + ARCHITECTURE 链路 F「BGM 已在后端预混 ducking，直接播放」。
4. **P2 冗余**：`api/projects.py:recommend_templates_endpoint` 把 `transcribe()` 包在 try/except 中（`transcribe` 设计为永不抛），fallback 还把 `media_path` 写绝对路径违反 D2；`fill.py:_pivot_unit_for(0, ...)` 第一参数 `gap_idx` 函数体内未使用；`fill.py` 通过修改原 gaps 列表的 `cur_gap.fill_result` 实现 side-effect 数据流；`mapping.py:gap_candidate` 事件 `ir_target.path="sections.0.gaps"` 但 mapping 不写 gaps（detect_gaps 才写）；`test_canvas_mismatch_produces_letterbox` 只测 vf 字符串、PLAN 1657 要求"模糊背景"未实现（当前只 black pad）。

**后果**：
不修 P1：渲染产物 MP4 段间黑屏 / 重叠、贴纸时机错位、BGM 盖过人声——三个加起来是「Phase 2 跑通了但产物不能用」。不修 P2：技术债累计、CI 假阳性、apply 流水线难重构。

**初步判断**：
已确认。Timeline 漂移用 fixture 数推过：用户 15s × 模板 voice 10s 的简单案例下渲染端必出黑屏/重叠。Sticker 坐标系问题用 grep 跨文件读出：skeleton.py 写绝对秒、renderer 减 ProjectIR 时间。BGM 缺失通过 grep `mix_bgm` 在仓库内只在 ffmpeg.py 定义 + lab dev 端点 + 0 处生产路径调用直接确认。

**关联**：
-> backend/app/apply/mapping.py（取消 banding；超 max 时截短 src_timerange）
-> backend/app/apply/style.py（新增 `_segment_output_span` + `style_for_segment` helper）
-> backend/app/apply/fill.py（接入同一 helper；删除死参；移除 in-place mutation）
-> backend/app/apply/pipeline.py（新 stage `bgm_mix`；outcomes → gaps.fill_result 显式写回；STAGE_TO_IR_PATH 增 bgm_mix 键）
-> backend/app/extract/skeleton.py（sticker 时间转 slot-local [0,1]）
-> backend/app/render/ffmpeg.py（normalize 增 `pad_mode="blur"` 模糊背景路径）
-> backend/app/api/projects.py（upload 用 blur；recommend 删死代码）
-> renderer/src/compositions/Project.tsx（sticker 直接用 segment-local 秒）
-> frontend/src/components/RemotionPlayer.tsx（sticker timeline 投影同步修正）
-> backend/tests/integration/test_apply_phase2.py（新增 timeline 连续性 / 截短 src / sticker remap / BGM mix / blur 五项测试）
-> backend/tests/unit/test_skeleton.py（新增 sticker [0,1] 归一化测试）
-> 004CHANGELOG.md [2026-06-09-6]

**解决方案**：
- **Timeline**：`mapping.py` 的 `timeline_cursor += output_span` 表达式必须与渲染端推算口径一致；取消 `min/max banding`；speed 钳到 1.2 后若 output 仍 > slot.max，截短 `src_end = src_start + slot.max × speed` 让 output 严格落在 max。新建 `style._segment_output_span(seg)` 作为单一真理源，mapping / fill / style / 渲染端全部经它读 output_span。
- **Sticker**：`extract/skeleton.py:_stickers_in` 把每枚 sticker 转换为 slot-local 归一化 `[0,1]` 时间；`apply/style.style_for_segment(slot, output_span)` 复制 StyleRule 时把 `[0,1]` 映射回 segment-local 秒；`fill.py` 的 `_wrap_segment_for` / `_reuse_segment_for` 同样走该 helper 而非裸 `slot.style.model_copy(deep=True)`。renderer `Project.tsx` 改为 `startSec={stk.start ?? 0}` 直接读，不再做坐标系减法；前端 `RemotionPlayer.tsx` 把 segment-local 秒投影回 timeline-global 秒后比较。
- **BGM ducking**：`apply/pipeline.py` 在 style 之后新增 stage `bgm_mix`，包在 `_safe` 中：`extract_audio(normalized, voice.wav)` → `mix_bgm(voice.wav, bgm_abs, bgm_ducked.aac, is_instrumental=template.audio.is_instrumental)`，写入 `ProjectIR.bgm_track = projects/{id}/bgm_ducked.aac`；失败降级为保留原 bgm_track（renderer 仍能播 un-ducked BGM）+ warning 事件。
- **P2 一并清理**：删 `api/projects.py:recommend_templates_endpoint` 内 `transcribe` 外层冗余 try/except + 绝对路径 fallback；`fill._pivot_unit_for` 删 `gap_idx` 死参；`fill_gaps` 不再 in-place mutate gaps（pipeline 用 `outcome.gap_idx → gaps[i].fill_result` 显式写回）；`mapping` 的 `gap_candidate` 事件 `ir_target.path` 改 `sections.0.segments`（与 fill 后落点一致）；`render/ffmpeg.normalize` 增 `pad_mode: "black" | "blur"` 二选一参数，`api/projects.py:upload_project` 走 `blur` 满足 PLAN 1657。
- **测试**：5 项新集成测试覆盖 timeline 连续性 / 截短 src / sticker [0,1] → segment-local 秒 / BGM mix 自动调用 / blur 滤波图，1 项 skeleton 单测覆盖 sticker 归一化。


---

## [ISS-014] Phase 2 端到端验证阻塞 — ASR 模型大小硬编码 + HF 缓存违背存储分类

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[功能异常]
**发现日期**：2026-06-09
**解决日期**：2026-06-09

**现象**：
对 ISS-012 落地的阶段 2 ★MVP 闭环走端到端验证（PLAN 1652 验证 9/10）：上传 15s 口播 → 点「推荐模板」→ 浏览器请求挂死，不返回任何推荐。后端日志见 `huggingface_hub` UserWarning：`The expected file size is: 3087.28 MB. The target location only has 1885.71 MB free disk space`，但 HF 没有 raise，继续下载。`backend/app/understand/asr.py:160` 写死 `whisperx.load_model("large-v3", ...)`；HF 默认缓存路径 `C:\Users\19123\.cache\huggingface\` 落在 C: 盘（系统盘 8.37 GB 自由），而 `DATA_ROOT=backend/data` 在 D: 盘（89 GB 自由）。recommend 端点同步 `await transcribe(...)` 卡在模型下载上。

**后果**：
不修：低磁盘机器无法跑通端到端（PLAN 验证 7/9/10 全部阻塞），开发者首次 onboarding 直接撞墙；即使磁盘够，模型下载也吃 C: 盘——违反 `001ARCHITECTURE §4 状态持久化分类`「重资产入 DATA_ROOT」的约定。架构上更深的问题：`Settings` 已经是项目「single source of truth」（`model_vlm` / `model_text` / `bgm_strategy` 全在内），唯独 ASR 模型选择例外，是范式断裂；HF cache 完全脱离 DATA_ROOT，是存储分类断裂。

**初步判断**：
已确认。`whisperx.load_model` 字面量 `"large-v3"` 在 `understand/asr.py:160`；`huggingface_hub` 的 HF_HOME 环境变量未被项目代码设置（grep `HF_HOME|HUGGINGFACE_HUB_CACHE|TRANSFORMERS_CACHE` 整个 backend 0 命中）；recommend 端点 `projects.py:122` 同步 `await transcribe()` 在 VLM 调用之前——ASR 失败时 VLM prompt 拼成 "(无)" 已经优雅降级，但 endpoint 仍强制等 ASR 完成。

**关联**：
-> backend/app/config.py（Settings 加 `asr_model` / `asr_device` / `asr_compute_type` / `hf_cache_dir` 四字段；`_apply_hf_env` 在 `get_settings()` 内统一注入 `HF_HOME` / `HUGGINGFACE_HUB_CACHE`）
-> backend/app/understand/asr.py（`_whisperx_run` 读 Settings 三字段而非字面量；fallback 事件 reasoning 写明当前 ASR_MODEL / HF_HOME 配置，运维不需读源码就能判断）
-> .env（新增 `ASR_MODEL=large-v3` / `ASR_DEVICE=cpu` / `ASR_COMPUTE_TYPE=int8` / `HF_CACHE_DIR=.cache/huggingface` 四行模板 + 注释）
-> .env.local（dev override `ASR_MODEL=small`，gitignored）
-> scripts/check_event_emission.py（顺手修：`EXEMPT_FILES` 从前缀匹配改为子串匹配，monorepo 化的 `backend/tests/` 与 repo-root `tests/` 一视同仁）
-> backend/tests/unit/test_config.py（新增 6 项单测：Settings ASR 默认 / env 覆盖 / `_apply_hf_env` 注入 / 已存在 env 不覆盖 / 空字符串 opt-out / `get_settings()` 端到端 wiring）
-> backend/tests/integration/test_apply_phase2.py（顺手修：补 `from pathlib import Path` 让 `_fake_extract_audio` 不再 NameError）
-> scripts/build_bgm_index.py（新增 BGM 索引生成脚本：librosa 提 BPM + ffprobe header 读 duration；幂等保留 mood_tag）
-> backend/data/system/bgm_pool/bgm_index.json（首次入库 3 首曲目索引；PLAN 1578 推荐 ≥ 5 但 nearest-neighbour 在 1 首以上即可工作，作为最小可用形态）
-> package.json（`dev:backend` 加 `--reload-dir app`：把 `--reload` 监听范围限制到源码目录，避免 HF 模型下载写入 `data/.cache/huggingface/` 时反复触发 uvicorn 重启 → ASR 永远跑不完）
-> 004CHANGELOG.md [2026-06-09-7]

**解决方案**：
- **Settings 加四字段**：`asr_model` 默认 `"large-v3"`（PLAN 1593 生产承诺不变），`asr_device` `"cpu"`，`asr_compute_type` `"int8"`，`hf_cache_dir` `".cache/huggingface"`（DATA_ROOT-relative，与 `system/bgm_pool` / `system/models` 同级，符合 §4 存储分类）。dev 通过 `.env.local` 覆盖 `ASR_MODEL=small` 即可绕开 3GB 下载。
- **HF env 注入点选 `get_settings()`**：项目所有路径都过 `get_settings()`（lru_cache 保证只执行一次），不引入新的初始化序点。`_apply_hf_env(settings)` 用 `os.environ.setdefault(...)` 写 `HF_HOME` + `HUGGINGFACE_HUB_CACHE`：保留运维显式 export 的优先级，`hf_cache_dir=""` 时整段跳过（HF 回到自己默认）。
- **asr.py 去字面量**：`_whisperx_run` 内 `from app.config import get_settings` lazy 读，传给 `whisperx.load_model`；fallback 事件 reasoning 写明当前配置 + HF_HOME 实际值，磁盘紧张时引导操作员去 `.env.local` 改 `ASR_MODEL=small`。
- **CI 守卫一并修**：`scripts/check_event_emission.py` 的 `EXEMPT_FILES` 模式从 `rel.startswith("tests/")` 改为 `"tests/" in rel`，monorepo 子目录下的 fixtures 现在能被正确豁免；同时 `test_apply_phase2.py` 补 `from pathlib import Path`（之前漏写，被 pipeline `_safe` 静默吞掉，伪装成 bgm_mix stage 失败）。
- **测试**：6 项 `test_config.py` 单测固化 Settings + `_apply_hf_env` 的所有语义路径（默认 / env 覆盖 / 注入 / setdefault 不覆盖 / 空串 opt-out / `get_settings()` 端到端）；全套 102 测试绿。



---

## [ISS-015] Phase 2.5 — NL 编辑 + 参数面板 + 工作台事件回放 + 提取历史入口

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[功能异常]
**发现日期**：2026-06-09
**解决日期**：2026-06-09

**现象**：
PLAN.md 1666-1759 声明阶段 2.5：用户用自然语言或参数面板改 ProjectIR → 自动重渲染拿新 mp4；前端 Visualize 页升级为工作台事件回放器；样例 / 项目详情页补「提取历史」区块 + 工作台顶栏补面包屑，把 task_id 唯一寻址升级为可寻址的目录视图。

落地前 backend 没有 `agent/nl_edit.py` / `api/edit.py` / `api/replay.py` / `render/throttle.py`，renderer 没有 cancel 路由，前端没有 NLBar / ParamPanel / PatchHistoryList / Visualize 页 / ExtractHistoryList / WorkbenchBreadcrumb。

**后果**：
不开 Phase 2.5 就停留在「一次性出片」的形态：用户对 apply 结果不满意只能重新跑一遍 apply（5+ 分钟），不能像剪辑软件一样微调；用户离开 Workbench 后再也找不到这次提取/编辑的入口（task_id 在 URL 里，URL 一关就丢）。Phase 2.5 直接对应 PLAN 1675「task_id 唯一寻址升级为有目录的可寻址」。

**初步判断**：
已确认。Phase 2 已经完成 ProjectIR 的 ★MVP 闭环；Phase 2.5 是在它的基础上加编辑链路 + 寻址表 + 回放能力，与 Phase 2 同结构。设计沿用 1B / 2 的 `_safe` 降级范式与 events.jsonl 真理源约定。

**方案讨论**（已确认，详见 `decisions/008-phase2-5-edit-storage.md`）：
- Undo：snapshot 栈代替 per-op inverse（每个 apply_patches 前把 project.json 拷贝到 snapshots/v{N}.json；undo 弹栈写回 + 删快照文件）。
- Patch 真理源：复用 events.jsonl（不引入 patch_history.jsonl），`GET /history` 查 nl_edit / panel_edit task 后聚合各 task events.jsonl 中 `stage="2.5.nl_edit"` 的事件。
- 渲染节流：`render/throttle.py` 30 行 `dict + asyncio.Lock` 实现项目级 supersede，renderer 端 `DELETE /render/{tid}` 配合做软取消（不引入独立 `agent/render_queue.py` 模块）。
- 工作台事件否决：保持为 UI 操作（`POST /workbench/{tid}/reject-event/{eid}` 产生 `stage="2.5.veto"` 事件）而非 Patch，避免把 UI 行为塞进 ProjectIR 编辑通道。

**关联**：
-> backend/app/agent/nl_edit.py（新增 — Text LLM NL→Patch / panel_to_patches / apply_patches 调度 / push_snapshot+undo / list_patch_history）
-> backend/app/api/edit.py（新增 — /edit / /panel-edit / /undo / /history 端点）
-> backend/app/api/replay.py（新增 — /replay/events / /replay/tasks / /replay/snapshot / /workbench/{tid}/reject-event/{eid}）
-> backend/app/api/projects.py（扩展 — /projects/{id}/tasks + /projects/{id}/lineage）
-> backend/app/api/samples.py（扩展 — /samples/{id}/tasks）
-> backend/app/tasks_store.py（扩展 — list_by_resource(kind, id) + idx_tasks_resource 复合索引）
-> backend/app/render/throttle.py（新增 — trigger_render_supersede）
-> backend/app/render/client.py（扩展 — cancel_render）
-> backend/app/main.py（扩展 — 挂载 edit / replay 路由）
-> backend/app/llm/prompts/2_5_nl_edit.md（新增 — NL → Patch system prompt + op 清单）
-> renderer/src/queue.ts（扩展 — registerRender / cancelRender / finalizeRender）
-> renderer/src/server.ts（扩展 — DELETE /render/:taskId）
-> frontend/src/api/index.ts（扩展 — nlEdit / panelEdit / undoEdit / listPatchHistory / listSampleTasks / listProjectTasks / fetchReplayEvents / snapshotAtSequence / fetchProjectLineage / rejectEvent）
-> frontend/src/components/ExtractHistoryList.tsx（新增 — 通用样例/项目历史列表）
-> frontend/src/components/workbench/WorkbenchBreadcrumb.tsx（新增 — 工作台顶栏面包屑）
-> frontend/src/components/editor/NLBar.tsx（新增 — Editor 底部 NL 输入栏）
-> frontend/src/components/editor/ParamPanel.tsx（新增 — Editor 左侧参数面板）
-> frontend/src/components/editor/PatchHistoryList.tsx（新增 — Editor 右侧编辑历史 + Undo）
-> frontend/src/pages/Editor.tsx（扩展 — 三栏布局 NL/Param/PatchHistory）
-> frontend/src/pages/Visualize.tsx（新增 — /projects/:id/replay 与 /samples/:id/replay 工作台事件回放器）
-> frontend/src/pages/Workbench.tsx（扩展 — 顶栏面包屑）
-> frontend/src/pages/SampleExtract.tsx（扩展 — useSearchParams + ExtractHistoryList）
-> frontend/src/pages/TemplateLibrary.tsx（扩展 — 详情页插入「本样例其它提取记录」）
-> frontend/src/main.tsx（扩展 — /projects/:id/replay 与 /samples/:id/replay 路由）
-> backend/tests/integration/test_nl_edit.py（新增 — per-op apply_patches / snapshot 栈 round-trip / lodash.set 语义 / list_by_resource 排序）
-> docs/decisions/008-phase2-5-edit-storage.md（新增）
-> 004CHANGELOG.md [2026-06-09-8]

**解决方案**：
按 PLAN 完整落地阶段 2.5：新增 `agent/nl_edit.py` 一文件覆盖 NL→Patch / panel→Patch / apply_patches / snapshot 栈 / list_patch_history 五个能力；新增 `api/edit.py` 与 `api/replay.py` 暴露 4+5 个端点；扩 `api/projects.py` 与 `api/samples.py` 加 history + lineage；扩 `tasks_store.py` 加 `list_by_resource` + 复合索引；新增 `render/throttle.py` 实现 project-level supersede + renderer 端 `DELETE /render/:taskId`；前端新增 3 个 Editor 子组件（NLBar / ParamPanel / PatchHistoryList）+ `Visualize` 回放页 + `ExtractHistoryList` / `WorkbenchBreadcrumb` 通用组件；扩 `Editor.tsx` / `Workbench.tsx` / `SampleExtract.tsx` / `TemplateLibrary.tsx` 挂载组件；新增 `2_5_nl_edit.md` Prompt；新增集成测试覆盖 PLAN 验证 1-8。决策详见 `decisions/008-phase2-5-edit-storage.md`。



---

## [ISS-016] 002STRUCTURE.md 对外部新人不友好 + 缺接口导览文档

**状态**：[已解决]
**优先级**：[P3 轻微]
**类型**：[体验]
**发现日期**：2026-06-10
**解决日期**：2026-06-10

**现象**：
`docs/002STRUCTURE.md` 在迭代过程中累积了大量内部细节：

- 阶段编号当主语：每行注释里穿插 `Phase 0.5 / Phase 1A / Phase 1B / Phase 2 / Phase 2.5 / Phase 5` 与 `D9 / D11 / D17 / D27 / D35 / D37 (2.5)` 等内部进度标签。新工程师不知道这些含义，第一眼读起来全是噪音。
- 内部术语裸露：`VisionEvent` / `IRTarget` / `Phase1AReport` / `StyleRule` / `output_span` / `supersede` 等内部概念直接当名词使用，没有平白话解释。
- 函数级别细节超纲：`_safe(label, field_key, coro)` / `SUBCAP_TO_IR_PATH` / `subscribe_with_snapshot` / `chat_vision_dual` 等可 grep 的函数 / 常量名也写进了目录文件，稀释了"导航"功能。
- 形态是一棵 ~250 行扁平树，没有目录段落分组与导语，新人想找"字幕识别在哪"得逐行扫树。
- `000README.md` 自己定的判断标准是"1 分钟内找到要改的代码"，目前文件做不到。

同时 `docs/` 下没有面向外部接入方的 HTTP 接口导览文档，新人理解后端能力只能逐个翻 `backend/app/api/*.py` 或者起服务后看 FastAPI `/docs`。

**后果**：
对外部接入工程师与新加入的内部工程师不友好。第一眼定位失败会显著拉长上手时间，且容易绕过 STRUCTURE 直接靠搜索代码摸索（违背文档定位）。接口侧没有"按场景串"的导览，外部接入方需要自己脑补"上传 → 推荐 → 应用 → 编辑 → 渲染"的调用顺序。

**初步判断**：
已确认。`000README.md` 已规定 STRUCTURE 的文体应是"目录树 + 一句话职责，纯描述、零分析"，当前文件违背这条规定。修复属于纯文档重写，不涉及任何代码逻辑。

**方案讨论**（已确认）：
- STRUCTURE 重写形态：保留目录结构，但按主目录分组（"目录分组式"），每个目录段落先有 2–4 句平白介绍，再列文件一句话——避免一棵无差别扁平树。
- 写作风格硬约束：删除所有 `Phase N` / `D1–D37` / `ISS-NNN` 标签；内部类型首次出现要平白解释；不写函数 / 变量 / 常量名（可 grep 的细节不进文档）。
- 占位标注：真占位（`agent/aigc.py` 等）显式标 `🚧 占位（计划中）`；dev-mode 闸门控制的功能（`api/dev_workbench.py` / `api/lab.py` / `WorkbenchLauncher.tsx` / `SubcapabilityLab.tsx`）不算占位，平白说明它们是开发模式入口即可。
- 接口文档：新增 `006API.md` 作为"带场景的接口导览"占位——按典型用户流程串接口（上传 / 提取 / 出片 / 编辑 / 实时回放 / 跨页导航），详细字段指向 FastAPI 自动生成的 `/docs`，不重复造 OpenAPI 已有内容。
- 不动 `001ARCHITECTURE.md`：本轮范围限定在 STRUCTURE + 新增 API 文档；ARCHITECTURE 里 D1–D37 列表的精简留待后续 issue。

**关联**：
-> docs/002STRUCTURE.md（重写 — 改成"目录分组 + 段落导语 + 文件一句话"形态；删除全部 Phase / D / ISS 内部进度标签；删除函数 / 变量名级别细节；内部类型首次出现平白解释；纠正 `motion.py` / `dev_workbench.py` / `lab.py` / `WorkbenchLauncher.tsx` / `SubcapabilityLab.tsx` 等已实现文件原误标的占位状态；补回 `docs/proposals/`、`vite-env.d.ts`、`ProjectHistoryStrip.tsx`、`StepCard.tsx` 等遗漏项）
-> docs/006API.md（新增 — 占位骨架 + 六条典型流程导览 + 开发模式接口 + 渲染器内部回调；详细字段指向 FastAPI `/docs`）
-> 004CHANGELOG.md [2026-06-10-1]

**解决方案**：
按外部读者视角重写 `002STRUCTURE.md`，结构由扁平树改为按主目录分组（每段先平白导语再列文件），全面剔除 Phase / D / ISS 等内部进度标签与函数级细节，对内部 IR / 事件类型在首次出现处给出平白解释。新增 `006API.md` 占位文档作为接口侧的"带场景导览"，留出待补充清单（请求示例、错误码、鉴权说明）由后续 issue 渐进填充。


---

## [ISS-017] Phase 2.6 — 工作台双时间轴 + 因果链 + ReplayClient 回归基础设施

**状态**：[已解决]
**优先级**：[P1 严重]
**类型**：[功能异常]
**发现日期**：2026-06-10
**解决日期**：2026-06-10

**现象**：
PLAN.md 1759-1870 声明阶段 2.6：把工作台从「事件列表 + 回放器」升级为四件事——壁钟甘特图视图（visx）、媒体时间线视图（视频时间轴 + 事件 marker + 播放头联动）、父子事件因果链可视化、events.jsonl 反向作 ReplayClient 回归测试基础设施。

落地前 backend 没有 `/api/tasks/{tid}/gantt` 与 `/media-timeline` 聚合端点、没有 `app/llm/replay_client.py`、没有 `scripts/record_golden.py` / `scripts/check_media_ts.py` / `tests/integration/test_golden_runs.py`、`VisionEvent` IR 没有 `media_ts` / `media_ts_range` 字段；前端没有 `WorkbenchGantt.tsx` / `WorkbenchMediaTimeline.tsx` / `CausalChainOverlay.tsx`，`Workbench.tsx` 没有 view 切换 + URL `?view=` 同步，`workbench.ts` store 没有 `view` / `currentMediaTs` / `hoveredChainRoot` 三个新态。

**后果**：
不开 Phase 2.6 工作台只能"按到达顺序看一长串卡片"，无法回答"AI 30 秒里到底干了什么"（甘特图）/ "视频第 N 秒 AI 做了什么决策"（媒体时间线）/ "AI 为什么这么决定，前置推理是什么"（因果链）。同时 events.jsonl 这份生产物缺乏机器可验证的回归测试——子能力代码 / IR 字段语义改动后只能靠肉眼 review 工作台，回归发现成本极高。

**初步判断**：
已确认。Phase 2.6 是项目可解释性的工程化收口阶段，PLAN 1771 表述为「方法论：工作台从'被动观测'升级为'AI 治理基础设施'」。设计沿用 1A / 1B / 2 / 2.5 已有抽象（事件总线 / `_safe` 降级 / events.jsonl 真理源），不引入新的状态层。

**方案讨论**（已确认，详见 `decisions/009-phase2-6-replay-and-dual-axis.md`）：
- ReplayClient 用 schema 验证过滤 FIFO 队列，不引入 `emitter` 字段（避免 schema 迁移 + 全部 entity event 发射点改造）。
- `_build_event` 始终写 `ir_value`（即使 ir_target=None），让 ReplayClient 不依赖额外字段就能复原 chat_vision 输出。
- 中栏因果链走 inline `ChainAnchorPill`（"↳ parent" / "↱ children"）+ `hoveredChainRoot` 跨视图 hover 同步，不在中栏画 SVG `<path>`（卡片纵向滚动列表里跨卡片虚线视觉噪音 > 信号）。SVG dashed 路径只在坐标映射型视图（甘特图 + 媒体时间线）画。
- 视图模式 3 选 1（list / gantt / media_timeline）而非 PLAN 文字提到的 5 选 1——`?view=ir` / `?view=frame` 在 list 模式下已经由现成 3 栏 UI 承载，独立 view 路径多余。
- 聚合落客户端（同日二次核查修订 PLAN 1790-1791）：甘特图 + 媒体时间线在 `frontend/src/lib/aggregateEvents.ts` 用纯函数 + `useMemo` 增量计算，不引入 `/api/tasks/{tid}/gantt` 与 `/media-timeline` 后端端点。SSE → store 已经是数据汇聚处，后端再投影一次会让 live 期间每条事件触发一次 fetch（长视频 500 事件即 500 次 HTTP），且 `_RESOURCE_DIRS` 与 `tasks.py` 重复违反 D1。

**关联**：
-> backend/app/ir/vision_event.py（VisionEvent 增 media_ts / media_ts_range；ir_value 语义放宽）
-> backend/app/llm/client.py（_media_ts_from_frames helper；_build_event 自动填 media_ts；fallback 路径填 media_ts；ir_value 始终落地）
-> backend/app/llm/replay_client.py（新增 — ReplayClient + ReplayExhaustedError）
-> backend/app/api/events.py（二次核查后聚合端点删除 — 仅保留 SSE + history endpoint）
-> backend/app/extract/{captions,stickers,masks,scenes,captions_anim,motion}.py（实体事件填 media_ts / 跨段事件填 media_ts_range）
-> scripts/record_golden.py（新增 — typer CLI 录制 golden_runs/{sid}/{events.jsonl, template.json}）
-> scripts/check_media_ts.py（新增 — CI 守卫：VisionEvent(frame_url=...) 必带 media_ts*）
-> backend/tests/integration/test_golden_runs.py（新增 — parametrize over golden_runs/ 子目录的 round-trip 回归）
-> backend/tests/unit/test_phase2_6.py（新增 — _media_ts_from_frames + ReplayClient 单测）
-> tests/fixtures/golden_runs/README.md（新增 — 录制 / review / commit / 何时重录的规范）
-> .github/workflows/ci.yml（新增 media_ts 守卫 + golden-runs job）
-> frontend/package.json（新增 @visx/{group,responsive,scale,text,zoom}）
-> frontend/src/state/workbench.ts（新增 view / currentMediaTs / hoveredChainRoot 三态 + setter；reset 不重置 view）
-> frontend/src/lib/aggregateEvents.ts（新增 — 客户端 buildGantt + buildMediaTimeline 纯函数；甘特图时间口径 start = (timestamp - duration) - origin）
-> frontend/src/lib/aggregateEvents.test.ts（新增 — vitest 覆盖时间口径 + 排序 + 颜色注入）
-> frontend/src/types/workbench.ts（VisionEvent 镜像增 media_ts / media_ts_range）
-> frontend/src/pages/WorkbenchGantt.tsx（新增 — visx wall-clock 甘特图 + 因果链 dashed path + zoom/pan + 外层 overflow-y-auto 纵向滚动）
-> frontend/src/pages/WorkbenchMediaTimeline.tsx（新增 — video-anchored marker timeline + 播放头联动 + scrub + scrub rect 放 SVG 子节点首位避免吞 marker click）
-> frontend/src/components/workbench/CausalChainOverlay.tsx（新增 — useChainResolver / useChainHighlight / ChainAnchorPill 三件套）
-> frontend/src/components/workbench/WorkbenchEventStream.tsx（事件卡片用 ChainAnchorPill 替代旧 parentLabel；改为 div role=button 以避免嵌套 button 警告；inChainHighlight 状态接入跨视图 hover sync）
-> frontend/src/pages/Workbench.tsx（顶栏 view 切换 segmented control；URL `?view=` 双向同步；list / gantt / media_timeline 三种全宽布局；videoUrl 透传给媒体时间线）
-> docs/future-plans/002-replay-old-recordings.md（新增 — Phase 2.6 之前 jsonl 的迁移占位）
-> docs/future-plans/003-gantt-virtualization.md（新增 — 甘特图大数据虚拟化占位）
-> docs/decisions/009-phase2-6-replay-and-dual-axis.md（新增 — 含同日二次核查后追加的决策 4：聚合落客户端）
-> 004CHANGELOG.md [2026-06-10-2]

**解决方案**：
按 PLAN 完整落地阶段 2.6：`VisionEvent` 加 `media_ts` / `media_ts_range` 双时间轴字段，`_build_event` 在调用客户端层按 frames 数自动填（1 frame → media_ts，>1 frames → range），实体事件 / 跨段事件由发射方显式填值；`_build_event` 顺手把 ir_value 始终写入解决 ReplayClient 复原难题。新增 `replay_client.py` 用 schema 验证从 events.jsonl 还原 chat_vision 调用（FIFO popleft + ValidationError → skip 实体事件 + ir_value=None+warning → 走 fallback 路径），完全不调网络。新增 `record_golden.py` typer CLI + `tests/integration/test_golden_runs.py` parametrize round-trip + `tests/fixtures/golden_runs/README.md`（录制 / 人工 review / 何时重录规范）；CI 加 `golden-runs` 与 `media_ts` 两步守卫。前端加 visx 五个模块化包；新增 `lib/aggregateEvents.ts` 提供 `buildGantt` / `buildMediaTimeline` 纯函数，配 `useMemo` 增量计算（同日二次核查后从 PLAN 提议的 backend 端点切回客户端聚合，避免 live 期间 N 次重复请求 + `_RESOURCE_DIRS` 跨 router 重复）；新增 `WorkbenchGantt.tsx`（visx ResponsiveContainer + scaleLinear / scaleBand + zoom + 因果链贝塞尔 dashed path + 外层 overflow-y-auto 纵向滚动；bar 时间口径 `start = (timestamp - duration_ms) - origin`、与 perf_counter 一致）/ `WorkbenchMediaTimeline.tsx`（顶部 `<video>` + 双向 sync 播放头 + ±0.5s 邻域高亮 + scrub rect 放 SVG 子节点首位避免吞 marker click + 因果链 dashed path）；`CausalChainOverlay.tsx` 用 `useChainResolver` / `useChainHighlight` / `ChainAnchorPill` 三件套实现"中栏 inline anchor + 跨视图 hover sync"——这是相对 PLAN SVG overlay 方案的第一性原理替代（决策详见 009 文档）；`Workbench.tsx` 顶栏加 3 选 1 segmented control + URL `?view=` 双向同步 + 切换不重 fetch + videoUrl 透传给媒体时间线。决策 / 已知代价 / Followup 详见 `decisions/009-phase2-6-replay-and-dual-axis.md`。

