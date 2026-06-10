# 目录结构

> 这份文档是 **新工程师第一次接手项目时的代码导航**：每个目录解决什么问题、装什么、想做某件事该去哪里。
>
> 阅读约定：
> - 模块之间的协作关系不在这里，去看 `001ARCHITECTURE.md`。
> - 接口请求 / 返回的具体字段不在这里，去看 `006API.md`（建设中）或后端 FastAPI 自动生成的 `/docs`。
> - 标注 🚧 的文件是已占位、计划中实现的；没有标注的就是当前可用的。
> - 测试文件 (`backend/tests/`、`*.test.ts`)、`__init__.py`、`__pycache__/` 等基础设施一般不在导航重点，仅在与功能定位相关时提及。
> - 文件 / 目录有增删时同步更新本文件。

---

## 根目录与配置

仓库是一个 pnpm workspace 组织的 monorepo，根目录下并列三个独立服务：`backend/`（Python FastAPI）、`renderer/`（Remotion 视频渲染）、`frontend/`（React 编辑器 UI）。`shared/` 放跨服务共享的类型定义，`scripts/`、`tests/`、`docs/` 是仓库级别的工具与文档。Node 侧用 pnpm 统一管理，Python 侧由 `backend/` 自己的 `pyproject.toml` 管。

- `PLAN.md`              当前阶段的执行路径，刚接手项目时先读它了解全局节奏。
- `README-PLAN.md`       `PLAN.md` 自身的写作规范，平时不用看，要修改 PLAN 时再读。
- `README.md`            仓库门面（占位标题）；真正的上手指南在 `docs/005DEVELOPMNET.md`。
- `taskRequirements.md`  课题原始需求书，写明产品目标与约束，做产品决策时回看。
- `package.json`         根 workspace 的入口，定义 `pnpm dev`、`pnpm gen:types` 等聚合命令。
- `pnpm-workspace.yaml`  声明 `renderer` 和 `frontend` 两个 Node 子包；`backend` 不属于 pnpm。
- `.env.example`         所有服务读取的环境变量样例（数据根目录、服务端口、LLM 凭据等），复制成 `.env` 后填值，`.env` 本身被 gitignore。
- `.gitignore`           标准 Python / Node 忽略规则，外加 `backend/data/`、生成的类型与 schema、测试视频素材。

### .github/workflows/

- `ci.yml`               GitHub Actions 配置，分四个 job：类型同步校验、Python 单测与守卫脚本、renderer 类型与测试、frontend 类型与构建。

---

## docs/  项目文档

文档采用编号体系，001–005 是常驻主文档，分别覆盖架构、目录结构、活跃问题、变更历史、首次上手；`decisions/` 沉淀已拍板的架构决策，`proposals/` 与 `future-plans/` 分别放讨论中的方案与远期规划。每次新对话开始前应先读 `000README.md` 和 `001ARCHITECTURE.md` 建立基本认知。

- `000README.md`           文档体系本身的使用说明，规定每个编号文档的职责与更新时机。
- `001ARCHITECTURE.md`     系统怎么运作、模块怎么协作，理解整个项目的入口。
- `002STRUCTURE.md`        本文件，代码与目录的导航地图。
- `003ISSUES.md`           当前活跃的问题清单及其状态。
- `004CHANGELOG.md`        按时间顺序的变更历史，回溯"什么时候改了什么"用。
- `005DEVELOPMNET.md`      第一次 clone 仓库的开发者按它一步步把三个服务跑起来。
- `006API.md`              🚧 占位（计划中）—— 带场景的接口导览，串起典型用户流程；详细字段查 FastAPI `/docs`。
- `decisions/`             已拍板的架构决策记录（ADR），每份回答"当时为什么这么决定、否定了哪些方案"。
- `proposals/`             讨论中尚未拍板的方案（如工作台 v4 设计、v3.1 一致性修复方案）。
- `future-plans/`          暂不实施但已识别的远期想法，避免被反复重新讨论。

---

## shared/

- `ir.schema.json`         backend 的 pydantic 模型导出的 JSON Schema，是 renderer 和 frontend 生成 TypeScript 类型的唯一源头；CI 自动生成，**已 gitignored**，本地需要先跑 `pnpm gen:types`。

---

## scripts/  CI 守卫与产物生成

仓库级别的 Python 工具脚本：一类是从后端 pydantic 模型导出共享 schema 给前端用，另一类是 CI 守卫，对后端代码做静态检查，确保关键约定（事件命名、事件发射、因果链字段等）不被悄悄破坏。本地提交前可以手动跑一遍。

- `gen_schema.py`              把后端的 IR 模型导出成 `shared/ir.schema.json`，前端类型生成的第一步。
- `build_bgm_index.py`         扫描 BGM 资源目录，生成检索用的索引文件供后端的 BGM 推荐使用。
- `record_golden.py`           录制回归基准：用真实模型跑一次模板抽取，把过程中的 AI 决策事件流和最终模板数据快照到测试夹具目录，用于后续代码改动后的"语义形状"对比。
- `check_stage_naming.py`      CI 守卫：保证 AI 调用发出的事件标签遵循统一命名规范。
- `check_event_emission.py`    CI 守卫：保证每个 AI 调用方法都至少广播一条事件。
- `check_parent_event_id.py`   CI 守卫：保证两段式 VLM 调用正确串联因果链字段。
- `check_media_ts.py`          CI 守卫：保证锚定到具体帧的事件同时记录视频侧时间锚点（媒体时间线视图渲染依赖此字段）。

---

## tests/fixtures/  测试用样例视频

跨语言、跨服务共用的测试视频素材（短样例、含字幕、含贴纸、含蒙版等不同特征的口播片段）。**整目录除 README 外都不入 git**——文件体积大、不适合版本控制；每位开发者按 README 自行准备本地副本，集成测才能跑起来。

### tests/fixtures/golden_runs/  AI 决策事件流回归基准

每个子目录对应一个样例的"上一次真实跑通"快照：一份完整的 AI 决策事件流（`events.jsonl`）+ 当时落到知识库的模板数据（`template.json`）。当模板数据的字段语义被改动后，CI 用回放型客户端按事件流复跑一遍，对比 IR 是否漂移；通过则说明改动只动了实现细节、没碰语义。子目录由 `scripts/record_golden.py` 录制后人工 review 入库，目录下的 `README.md` 记录录制 / 审核 / 何时重录的规范。

---

## backend/  顶层配置与数据目录

后端是 Python FastAPI 服务，所有运行时产物（用户上传、提取结果、渲染输出、数据库、日志）都落在 `backend/data/`，便于一键清理与备份。代码本身在 `backend/app/`（见后续章节），测试在 `backend/tests/`，根级只有少量配置。

- `pyproject.toml`         后端 Python 包定义：依赖清单（FastAPI、pydantic、httpx 等）、可选的重型 ML 依赖组、pytest 配置。新建 venv 后用 `pip install -e .[dev]` 安装。
- `ruff.toml`              Python 代码格式与 lint 规则（行宽 100、Python 3.11、启用一组常用检查），CI 与本地保持一致。
- `data/`                  默认的数据根目录，**整目录被 gitignore**。运行时分几类落地：`samples/` 用户上传的样例视频与提取产物；`projects/` 用户项目（实例化的时间线、渲染产物、编辑历史）；`system/` 字体、BGM 池等系统资源；`aigc/` AI 生成的贴纸与 B-roll 缓存；`kb.sqlite` 模板知识库数据库；`logs/` 运行日志。可通过 `.env` 的 `DATA_ROOT` 改到别处。

### backend/tests/

后端测试分两层：`unit/` 是不依赖外部资源的纯单测，覆盖 IR 模型、配置、事件总线、知识库、LLM 客户端、各子能力函数等；`integration/` 是端到端链路测，跑真实的提取、编辑、应用流程，依赖 `tests/fixtures/` 下的视频素材。

- `conftest.py`            pytest 公共夹具，主要为每次会话准备一份临时的 `DATA_ROOT`，把 `tests/fixtures/` 的素材复制进去，避免污染本地数据目录。
- `unit/`                  单元测试：覆盖 IR 数据模型与 schema、配置加载、事件总线、知识库存储、LLM 客户端封装、各子能力函数、CI 守卫脚本本身等。
- `integration/`           集成测试：覆盖完整的提取链路、应用链路、自然语言编辑链路，以及子能力输出的形状校验，需要本地准备好 fixtures 才能通过。

---

## backend/app/  应用入口与基础设施

后端 FastAPI 应用的根目录。新人启动服务、调整全局配置、追踪一次 AI 调用从产生到落盘到推送前端的链路时，会先来这里。装的是"任何子模块都可能用到的东西"：进程入口、配置、日志、事件总线、任务表。

- `main.py`            FastAPI 应用入口，挂载所有路由、初始化数据目录、串接事件总线与任务表。
- `config.py`          从 `.env` / `.env.local` 加载全局设置（数据根目录、各服务地址、模型名、AI 开关等）。
- `logging.py`         结构化日志（JSON 输出）的初始化与取用入口。
- `cli.py`             本地开发用的命令行工具，把素材文件拷进 `samples/` / `projects/` 目录并做归一化（需要 `ENABLE_CLI_INGEST` 才开启）。
- `event_bus.py`       进程内的"AI 决策事件总线"：每次 AI 调用产出的事件先在这里广播，再分别落到 JSONL 文件、推给浏览器的 SSE 订阅者。
- `tasks_store.py`     后台任务表（SQLite）的封装，记录每个长耗时任务的状态、进度、所属资源、事件文件路径。

### backend/app/api/  HTTP 路由层

所有对外暴露的 HTTP / SSE 端点都注册在这里。每个文件对应一类资源或一个使用场景，新人想加接口、查接口契约、排查前端报错时先打开对应文件。文件本身只做参数校验和编排，真正的算法逻辑在 `agent/` `extract/` `apply/` `render/` 等姊妹目录。

- `samples.py`         样片上传与归一化接口，以及一个最小化的渲染示例端点。
- `projects.py`        用户项目主线接口：上传素材、模板推荐、装配生成、查看项目数据、触发渲染、获取播放器属性、混入背景音乐。
- `templates.py`       模板库（KB）的增删改查与事件流接口。
- `tasks.py`           任务状态查询接口，并接收渲染器回调的进度 webhook。
- `events.py`          AI 决策事件的 SSE 推送流和历史事件回放接口，是前端工作台所有视图（事件流、甘特图、媒体时间线）的统一数据源。聚合视图的"按子能力分轨道""按视频时刻定位"由前端从同一份事件流投影出，后端不再做平行投影。
- `edit.py`            项目编辑接口：自然语言改稿、面板直接改、撤销、查看改动历史。
- `replay.py`          按项目 / 素材 id 拉取一个任务跑过的全部事件，并可重建任意时间点上的中间产物，供前端"时间线回放"页使用。
- `dev_workbench.py`   开发模式下的模拟事件流入口：让前端工作台在没有真实 AI 调用时也能联调（需打开 `ENABLE_DEV_MOCK`）。
- `lab.py`             开发模式下的"单点能力实验室"后端：选一份样例 + 一个识别子能力跑一次，实时观察事件流（需打开 `ENABLE_DEV_MOCK`）。

### backend/app/ir/  系统的"数据形状"定义

整个后端共享的数据结构都在这里以 pydantic 模型形式定义：识别中间产物、可复用模板、最终项目时间线、AI 事件、编辑操作。前端 TypeScript 类型和渲染器的 zod 校验都从这里 codegen 出去，所以这是数据契约的唯一真源。新人想知道"某个字段叫什么、嵌在哪一层、谁能改"就来这里。

- `ledger.py`              逐字带时间戳的语音转写结果（文本本身不可变，只允许 AI 改字号划分）。
- `template.py`            可复用的"风格配方"模板：骨架槽位 + 各类风格规则 + 标签。
- `project.py`             最终装配出来的项目时间线数据（剪辑片段、字幕轨道、背景音乐等），渲染器吃它出 MP4。
- `phase1a_report.py`      视频素材识别阶段的中间报告，把切镜、画面字幕、贴纸、调色、镜头运动等多个子能力的结果汇总到一棵树上。
- `vision_event.py`        一次 AI 决策的结构化记录：模型输入摘要、输出、置信度、要写入哪份数据的哪个字段；事件总线广播的就是它。
- `patch.py`               统一的"编辑操作"数据结构：自然语言改、面板改、人工审核改都翻译成它。
- `path_validator.py`      校验事件里引用的字段路径是否真的指向某个模型的真实字段，避免前后端字段错位。
- `export.py`              把本目录所有顶层模型聚合导出成一份 JSON Schema 文档，供前端 / 渲染器代码生成对齐。

### backend/app/extract/  视频原始信号识别

把一段输入视频拆成机器可读的结构化信号——分镜、字幕、贴纸、缩放、转场、蒙版、调色、配乐——是后续模板生成与剪辑推荐的"眼睛"。文件按视频维度拆分：每个 .py 负责识别一类视觉/听觉要素，对外提供 `detect_*` / `classify_*` 异步函数，返回结构化结果与一串可观测事件。新人想加一种新的识别能力（比如人脸表情），就在这里加一个新文件并接进 `pipeline.py` 的 DAG。

- `context.py`             一次抽取的共享上下文对象，把分镜、采样帧、LLM 客户端缓存起来，避免子识别器重复跑 PySceneDetect / ffmpeg。
- `frame_sampler.py`       用 ffmpeg 按 1fps + 切点附近 ±0.2s + 每镜头首中末帧抽 JPEG。
- `scenes.py`              用 PySceneDetect 切分镜头，给每个 scene 输出代表帧供工作台预览。
- `captions.py`            调用 VLM 在采样帧上识别字幕的位置、字号、颜色、描边、动画类型，跨场景去重合并。
- `captions_anim.py`       用 OpenCV 帧差和光流精修字幕入场动效（逐字弹入 / 整句滑入 / 淡入 / 打字机）。
- `stickers.py`            VLM 网格采样识别贴纸的位置、语义类别，再用 Canny + 帧差细修边界框。
- `motion.py`              VLM 粗判每个分镜的镜头缩放方向（推进 / 拉远 / 稳定），非稳定的再用光流估出关键帧曲线。
- `transitions.py`         VLM 看相邻 scene 边界前后三帧，分类转场类型（硬切 / 叠化 / 滑动 等）。
- `masks.py`               几何蒙版识别：CV 主路径（HoughCircles / Canny 矩形 / HoughLinesP）+ VLM 兜底。
- `color.py`               VLM 给主观调色标签 + LUT id，OpenCV 算 HSV 直方图作为数值佐证。
- `audio.py`               用 Demucs 分离人声/伴奏 + librosa 算 BPM、能量曲线、情绪标签，得到背景音乐画像。
- `skeleton.py`            把上面所有识别结果按时间位置归并成"开头 / 主体 / 结尾"三段骨架，每段挂上对应的字幕、贴纸、缩放、蒙版、转场样式。
- `pipeline.py`            把所有识别器编排成一个 DAG，统一处理并发、降级、事件汇总，最后产出模板数据并写入知识库。

### backend/app/understand/  语音与高层语义理解

视觉识别之外的两条理解通路。`extract/` 关心"画面里有什么"，这里关心"声音说了什么、字幕在干什么"，输出供后续口播匹配与字幕功能识别使用。

- `asr.py`                 WhisperX large-v3 中文转写 + 词级时间戳 + 强制对齐，按 0.3s 停顿合并出语句单元；模型缺失时降级为按时长均匀切块，并打降级事件。
- `vision.py`              字幕功能分类器：拿 `extract/captions.py` 已识别的字幕条目，调一次 VLM 判断功能（强调 / 标题 / 旁白 / 普通…）。

### backend/app/llm/  大模型调用层

所有对外 LLM / VLM 调用统一从这里出去。新人接入新模型、调超时、改重试策略，都改这一处即可。客户端层会自动计时、把每次调用包装成可观测事件、在凭据缺失或上游连错三次时退化成空 schema 兜底，保证识别管线不会因为单次网络故障整体崩掉。

- `client.py`              LLM/VLM 客户端：抽象基类 + OpenAI 兼容适配器（Qwen-VL / GPT-4o / 本地 vLLM）+ 原生 Anthropic 适配器，统一处理结构化输出校验、计时、事件发射、降级兜底。
- `replay_client.py`       回放型客户端：用一份历史录制的 AI 决策事件流当作"真值"，把每次结构化输出还原回来；不调网络也不调真实模型，专门用来在代码改动后做"语义形状"回归测试。

#### backend/app/llm/prompts/  提示词模板

按"识别能力"组织的 markdown 提示词文件，每个 .md 对应一个识别 / 推荐场景的 system prompt，由模块入口按文件名加载并缓存。改提示词不需要动 Python 代码，直接编辑对应 .md 即可。

- `scenarios/`             端到端验收用的示例任务 JSON（字幕、贴纸、整套抽取 demo），用于本地跑通完整链路时的固定输入。

### backend/app/kb/  模板库

模板是从样例视频中提取出来的"剪辑骨架"（一连串镜头槽位 + 字幕 / 贴纸 / 转场风格）。这个目录负责把模板存进 SQLite、给模板打标签、做质量复查，以及在用户上传素材时挑出最合适的模板。新人想新增一种推荐策略、调整模板存储字段、或者改打标签的提示词，都来这里。

- `store.py`               模板的持久化层：在 `data/kb.sqlite` 里维护一张 `templates` 表，提供新增、查询、按 ID 取详情等接口。
- `tagging.py`             模板标签合成：让视觉模型从位置、功能、场景、备注四个维度给模板打标签，结果写回模板数据。
- `sanity.py`              模板整体复查：抽几张代表帧，让视觉模型判断这个模板的骨架顺序、字幕占位、缩放参数是否自洽。
- `recommend.py`           推荐入口：把用户素材的几帧抽样 + 语音摘要丢给视觉模型，让它在整个模板库里挑出排名靠前的几个并给出中文理由。
- `select.py`              简版选模板器：按标签精确匹配返回最相似的一条，作为推荐链路的兜底选项。

### backend/app/apply/  自动出片装配

"用户素材 + 选中模板 → 最终可渲染视频结构"的核心装配线。每个文件对应装配流水线的一个环节，串起来就是把一段口播按模板的节奏切片、补缺、上字幕和贴纸。新人想调整素材匹配规则、新增补缺策略、改字幕样式来源，主要工作在这里。

- `mapping.py`             按时间顺序把用户语音切片绑定到模板的镜头槽位，并按槽位时长计算变速（限制在 ±20%）。
- `gaps.py`                识别哪些模板槽位没有用户素材覆盖，标记为待补缺的"缺口"，区分口播缺口和包装类缺口。
- `fill.py`                给缺口补内容：三种策略——文本模型生成补字幕、用占位风格做"包装型"片段、或复用相邻片段尾帧做停留。
- `style.py`               把模板里每个槽位的样式（字幕、缩放、贴纸、转场、调色）套到对应片段上，并选定背景音乐。
- `pipeline.py`            装配流水线总控：依次跑归一化、语音识别、绑定、缺口、补缺、上样式、存盘，并把任何一步的失败信息收集到产物的"降级标记"里，不中断后续步骤。

### backend/app/agent/  编辑代理

用户拿到自动出的初版视频后，会通过自然语言（"把第二段字幕字号调大点"）或参数面板做局部调整。这个目录负责把编辑请求落到项目数据上，并提供撤销能力。新人想接入新的编辑指令类型、调整撤销策略，从 `nl_edit.py` 入手。

- `nl_edit.py`             自然语言 / 面板编辑核心：把指令翻译成结构化编辑指令并应用到项目数据，应用前先把旧版项目快照存盘以便撤销，同时把每次编辑过程广播给前端工作台。
- `aigc.py`                🚧 占位（计划中）—— 贴纸图片、B-roll 视频等 AIGC 生成接口，目前只返回 None。

### backend/app/render/  渲染基础设施

视频最终输出依赖两个外部能力：本地 ffmpeg（做转码、归一化、缩略图等基础处理）和一个独立的 Node 渲染服务（Remotion 把项目数据出成最终 MP4）。这个目录是这两者的封装层，外加一个防止重复渲染的节流器。新人想调整渲染参数、对接新的渲染后端、或者改连续编辑时的渲染合并策略，来这里。

- `ffmpeg.py`              ffmpeg / ffprobe 命令行封装：读媒体信息、归一化分辨率帧率、做黑边或模糊背景填充、抽缩略图。优先用系统 ffmpeg，找不到则回退到 imageio-ffmpeg 自带的二进制。
- `client.py`              通过 httpx 调远端渲染服务的 HTTP 客户端，支持发起渲染、取消渲染、健康检查。
- `throttle.py`            项目级渲染节流：用 `asyncio.Lock` 保证同一项目同时只有一个渲染在跑，新的渲染请求会自动取消旧任务，避免连续编辑时排队堆积。

---

## renderer/  视频渲染服务（Node + Remotion）

一个独立运行的 Node 进程，监听 `RENDERER_PORT`（默认 8001），接收后端推过来的项目数据并把它渲染成最终的 mp4 文件。内部用 Remotion + 无头 Chromium 把 React 组件逐帧渲染成视频，再用 ffmpeg 编码成 H.264。后端只负责生成项目描述并 POST 过来，进度通过回调写回后端的 `/api/internal/task-progress`，渲染好的文件落到共享数据目录里供前端预览。

顶层只有 TypeScript 工程的标配：`package.json`（依赖 Remotion、Express、pino、p-queue、zod 等）、`tsconfig.json` / `tsconfig.build.json` 配置编译。

### renderer/scripts/

- `gen-types.ts`           从 `shared/ir.schema.json` 生成 TypeScript 类型 + zod 校验代码，让渲染端和后端共用同一份数据结构定义。

### renderer/src/

- `server.ts`              渲染服务的 HTTP 入口；提供健康检查、查询渲染队列、提交渲染任务、按任务 ID 取消任务四个接口。
- `render.ts`              单次渲染的主流程：解析素材路径成可访问 URL、调 Remotion 打包页面、计算画布参数、逐帧渲染并写出 mp4，途中向后端汇报进度。
- `queue.ts`               渲染任务的串行队列（一次只跑一个，避免无头浏览器互相抢资源），同时维护每个任务的取消标记，用于"自动取消旧渲染"。
- `progress.ts`            把渲染过程中的进度百分比和阶段名回传给后端的小工具。
- `preflight.ts`           渲染前的资源体检：扫描项目里引用到的用户素材、背景音乐、贴纸图等，逐一确认文件存在；缺哪个就直接报错，避免渲染出半截画面是 404 的废片。
- `logger.ts`              日志封装（pino），统一附带服务名和任务 ID 字段。
- `paths.ts`               解析数据根目录、把项目里的相对路径转成绝对路径的小工具。
- `remotion.root.tsx`      Remotion 的入口注册文件，把根组件挂上去。
- `types/ir.ts`            生成产物（gitignored）：由 `scripts/gen-types.ts` 从共享 schema 生成的 zod schema + TS 类型。

### renderer/src/compositions/  渲染组件

按视觉元素拆分的渲染组件，每个文件负责一种叠加层；最外层 `Project.tsx` 把它们按"全局调色 → 每段视频 + 缩放 + 贴纸 + 蒙版 → 顶层字幕 → 背景音乐"的顺序组合起来。

- `Root.tsx`               Remotion 的根组件，声明可渲染的合成；画布尺寸、帧率、总时长由项目数据动态推导。
- `Project.tsx`            把项目数据组合成一段完整的可渲染时间线（用户素材、字幕、贴纸、蒙版、缩放、调色、背景音乐都在这里编排）。
- `projectMeta.ts`         从项目数据里推导画布尺寸、帧率和总时长的小工具，给 Root 和渲染日志共用。
- `Caption.tsx`            字幕条渲染组件，支持模板预览（占位文案）和正式输出（真实台词）两种模式，带描边和入场动画。
- `Sticker.tsx`            贴纸渲染组件；有图就放图，没图则画一个明显的占位框提示"此处待生成图片"。
- `Mask.tsx`               几何蒙版叠加层（圆形 / 矩形 / 上下分割），把蒙版外的区域压暗以突出主体。
- `ZoomLayer.tsx`          根据关键帧曲线对单段视频做平滑缩放推拉的包裹层。
- `ColorLayer.tsx`         整片调色层，把语义化色调标签（暖调、冷调、电影感）映射成一组 CSS 滤镜。

---

## frontend/  前端（React + Vite）

浏览器单页应用，开发态由 Vite 起在 `5173`，所有数据请求都打到后端的 `/api`，所有素材资源（视频、JPEG 帧、字幕字体等）走 `/data`，由 Vite 代理转发到 FastAPI。代码分五块：`pages/` 是路由级页面、`components/` 是可复用 UI、`state/` 是全局状态、`api/` 是后端调用封装、`styles/` 是设计令牌与全局样式。它围绕两条主线展开：「上传素材 → 推荐模板 → 出片 → 编辑」的出片流程，以及「实时观看 AI 决策每一步」的透明工作台。

顶层是标准 Vite + React + Tailwind + Vitest 配置（`package.json` / `vite.config.ts` / `tailwind.config.ts` / `tsconfig.json` / `vitest.config.ts` / `postcss.config.js` / `test-setup.ts` / `index.html`），新人只在改构建或调试 Tailwind 时才需要看。

### frontend/scripts/

- `gen-types.ts`           从 `shared/ir.schema.json` 生成 `src/types/ir.ts`（zod schema + TS 类型），保证前后端共用同一份视频结构定义。

### frontend/src/

- `main.tsx`               应用入口。挂载 `<BrowserRouter>`、注册全部路由（样例提取、模板库、出片编辑器、工作台、复盘页、Dev 入口）、提供顶部带导航的统一外壳；访问 `/` 重定向到 `/sample-extract`，Dev 路由仅在开发构建下挂载。
- `vite-env.d.ts`          Vite 客户端类型声明，让 `import.meta.env` 可解析。

### frontend/src/api/  接口封装

浏览器到后端的 HTTP 客户端封装（基于 axios 与浏览器原生 EventSource / SSE），所有页面只通过它访问后端，不直接拼 URL。

- `index.ts`               汇总导出。封装上传素材、模板推荐、应用模板、查询和触发渲染、自然语言编辑、参数面板编辑、撤销、读取编辑历史、按序号回放快照、查询素材族谱、否决某条 AI 事件等所有 REST 接口。
- `events.ts`              工作台事件流订阅。基于 SSE 长连接订阅一个任务的 AI 决策事件（断线由浏览器自动重连），并提供历史回放接口与 Dev 模拟流的启动入口。
- `templates.ts`           模板库接口封装：触发提取、列模板、读模板详情、改标签 / 字幕占位、删模板、读单个模板的提取事件流。
- `lab.ts`                 单点能力实验室接口封装：列出全部子能力、用某个样例素材跑单步检测、读取基线 JSON 用于对比。

### frontend/src/state/  全局状态

基于 Zustand 的两个轻量 store。

- `index.ts`               存当前关注的后台任务状态，给跨组件的 loading / 错误条用。
- `workbench.ts`           工作台核心 store：保存事件流、根据事件实时累积出的视频结构快照（用 immer + lodash 做不可变更新）、当前选中事件、用户否决标记、过滤范围、暂停 / 跟随状态、视图切换。事件按 ID 去重，所以 SSE 直推和历史回灌可以并行不冲突。

### frontend/src/lib/  纯函数工具

不依赖 React、不依赖 store、可单独 unit-test 的派生计算工具。

- `aggregateEvents.ts`     工作台事件流聚合器：从同一份事件数组分别投影出"按子能力分轨道（壁钟时间）"和"按视频时刻定位（视频时间）"两个形状。两个视图都用 `React.useMemo` 包它，事件变更时增量重算，不调后端聚合接口。

### frontend/src/components/  可复用组件

跨页面复用的展示与交互组件。

- `RemotionPlayer.tsx`             浏览器内的视频预览。基于 HTML `<video>` 加 CSS 叠加字幕、缩放、贴纸，无需打包 Remotion 编排代码就能 1:1 模拟最终成片，给编辑器实时预览用。
- `TaskProgress.tsx`               通用的后台任务进度条：每秒轮询一次任务状态，跑完或失败时回调宿主组件。
- `ExtractHistoryList.tsx`         给样例 / 出片项目页用的"过往任务"列表：列出该资源的所有提取 / 编辑 / 渲染任务，每条都是回到工作台的链接。

#### frontend/src/components/editor/  出片编辑器三栏组件

出片页用到的左 / 中 / 下 / 右组件，配合主页面构成"参数面板 + 实时预览 + 自然语言指令 + 历史"的工作流。

- `NLBar.tsx`                      底部自然语言指令输入框：用户敲"字幕改黄色"等回车，调后端做一次自然语言编辑并通知主页面刷新预览。
- `ParamPanel.tsx`                 左侧参数面板：把字幕颜色 / 动画 / 位置、节奏、画布尺寸、BGM 等做成可视控件，每个控件改动直接调后端的面板编辑接口。
- `PatchHistoryList.tsx`           右侧编辑历史：逆序列出本项目每次编辑，每条带跳到工作台的链接，顶部按钮做撤销。
- `ProjectHistoryStrip.tsx`        编辑器顶部的"最近项目"横向条，点一下即可切换历史项目，当前项目以高亮形式保留在条上。
- `StepCard.tsx`                   数字编号的步骤卡容器，给出片页和样例页的多步流程做统一外观（编号徽章 + 状态色 + 标题 + 内容槽）。

#### frontend/src/components/workbench/  AI 透明工作台三栏组件

工作台页用到的左中右三栏视图组件，目标是把 AI 的每一次"看 / 想 / 改"都展示出来。

- `WorkbenchVisionPane.tsx`        左栏画面视图：默认放选中事件的单帧截图并叠检测框，可一键切到完整视频回放。
- `WorkbenchEventStream.tsx`       中栏事件流列表：按阶段分组或按到达顺序展示每条事件的徽章 / 摘要 / 严重度边线，每张卡片底部挂上跳到父事件 / 子事件的小锚点，支持选中、否决、跟随最新事件。
- `WorkbenchIRPane.tsx`            右栏视频结构树：基于 react-arborist 把当前累积出的视频结构以可折叠树展示，叶子节点显示截断后的字段值预览。
- `WorkbenchBreadcrumb.tsx`        顶栏面包屑：根据任务的资源类别拼出"样例 > xxx > 提取任务 #abc"或"项目 > xxx > 应用任务 #abc"。
- `CausalChainOverlay.tsx`         因果链组件库：暴露三个东西——把事件 ID 解析成"父事件 / 直接子事件"的列表、计算"被悬停事件链路上所有相关事件 ID"的集合、可点可悬停的小锚点。中栏卡片以及甘特图、媒体时间线都共用，让"在中栏 hover 一个父事件链接"能在其他视图里同步亮起对应的横条 / marker。
- `EventBadge.tsx`                 按阶段前缀渲染不同底色的徽章，颜色统一来自 CSS 变量。
- `BboxOverlay.tsx`                把归一化的检测框换算到帧的真实像素并以 SVG 叠在画面上。

### frontend/src/pages/  页面

每个文件对应 `main.tsx` 里注册的一条路由。

- `SampleExtract.tsx`              起始页（`/sample-extract`）。上传一段口播视频，看到时长 / 流信息，可一键试渲染或触发模板提取，下方列出该样例的历史任务。
- `TemplateLibrary.tsx`            模板库（`/templates` 列表 + `/templates/:id` 详情）。详情页能改标签和字幕占位、删除模板，并提供回到工作台看本模板提取过程的入口。
- `Editor.tsx`                     出片编辑器（`/editor` 与 `/editor/:projectId`）。串起完整出片流程：上传素材 → 取推荐 → 选模板应用 → 进入三栏（参数面板 / 实时预览 / 编辑历史）边看边调 → 渲染最终 MP4。
- `Workbench.tsx`                  实时工作台（`/workbench/:taskId`）。挂上 SSE 实时拿事件，同时拉一遍历史事件回灌做兜底，喂进 store 后渲染顶部面包屑；顶栏带三选一切换器（三栏列表 / 壁钟甘特图 / 媒体时间线），URL `?view=` 参数双向同步以便分享链接保留视图。
- `WorkbenchGantt.tsx`             壁钟甘特图视图（`?view=gantt`）。用 visx 把每个子能力画成一条横向轨道，事件以横条 / 竖线落点；父子事件之间画虚线贝塞尔曲线展示推理链；支持滚轮缩放、拖拽平移。给 AI 工程师快速看清"30 秒里到底跑了哪些子能力、谁先谁后"。
- `WorkbenchMediaTimeline.tsx`     媒体时间线视图（`?view=media_timeline`）。顶部嵌入原视频，下面是按视频秒为横轴的事件 marker——单帧锚点画三角形、跨段事件画半透明矩形条；播放头在哪一秒就高亮邻近 marker，点击 marker 把视频跳到对应秒同时选中事件。给创作者 / 产品视角看"视频第 N 秒 AI 都在做什么决定"。
- `Visualize.tsx`                  复盘页（`/projects/:projectId/replay` 与 `/samples/:sampleId/replay`）。从后端拉某个任务的全部事件 JSONL，按选定速度重新喂进同一个工作台 store，达到"重播一遍"的效果，并支持一键 MediaRecorder 录屏导出。
- `WorkbenchLauncher.tsx`          开发模式入口（`/workbench/dev`）。列出所有内置 mock 场景，点一下让后端按脚本广播一串假事件，便于在没有真实视觉模型时调试三栏 UI。
- `SubcapabilityLab.tsx`           开发模式单点能力实验室（`/lab`）。挑一个子能力 + 一个样例跑单步检测，跳到工作台查看结果并对照基线。

### frontend/src/types/

- `ir.ts`                          生成产物（gitignored）：由 `scripts/gen-types.ts` 从 `shared/ir.schema.json` 生成的 zod schema 与 TS 类型，前后端共用。
- `workbench.ts`                   工作台事件、阶段、检测框等结构的 TS 接口定义；手写一份与后端镜像，避免新人拉下代码立即能跑、不必先做代码生成。

### frontend/src/styles/

- `tokens.css`                     设计令牌（CSS 变量）：统一定义颜色、字体、间距、圆角、阴影，以及工作台事件徽章的阶段调色板。所有页面共用，禁止页面级配色。
- `global.css`                     全局样式入口：引入 `tokens.css`、Tailwind 三件套、基础排版，以及少量复用类（卡片、主按钮、ghost 按钮、检测框脉冲、事件入场动画等）。
