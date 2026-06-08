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

