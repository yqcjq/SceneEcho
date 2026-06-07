# tests/fixtures/

测试用视频素材**不入 git**（体积大、二进制不适合版本控制）。每位开发者按下表自行准备。

## 必需 fixtures

| 路径 | 时长 | 内容要求 | 用于 |
|------|------|---------|------|
| `sample_basic_15s/source.mp4` | 5–20s | 含字幕 + BGM + 1 处缩放 | Phase 0 / Phase 1 提取测 |
| `short_15s/source.mp4` | 10–20s | 一镜到底口播 | Phase 0 / Phase 2 应用测 |

## 后续阶段 fixtures（按需补）

| 路径 | 时长 | 内容 | 引入阶段 |
|------|------|------|---------|
| `sample_with_sticker_12s/source.mp4` | ~12s | 含 1 个明显贴纸 | Phase 1 |
| `sample_fast_pace_8s/source.mp4` | ~8s | 3+ 切点的快节奏 | Phase 1 |
| `sample_no_bgm_10s/source.mp4` | ~10s | 无 BGM | Phase 1 |
| `test_short_complex_18s/source.mp4` | ~18s | 多句口播 + 1 处口误 | Phase 2 |

## 与 backend/data/ 的关系

- `tests/fixtures/` = 仓库级测试素材源（你手动放）
- `backend/data/samples/` = 运行时数据（后端上传/ingest 后自动落盘，gitignored）

`backend/tests/conftest.py` 会在 pytest session 启动时把 `tests/fixtures/` 下的素材复制到临时 DATA_ROOT，单测无副作用。

## CI

阶段 0 单测不依赖 fixtures。集成测试（Phase 1+ 引入）会在 self-hosted runner 上准备好这些素材。
