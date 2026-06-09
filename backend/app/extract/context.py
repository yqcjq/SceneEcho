"""Phase1AContext — 一次抽取的共享上下文，子能力共用 scenes / frames cache。

Phase 1A 第一版每个子能力函数取「自由参数」（normalized_path + frames + task_id）
导致 lab.py runner 必须重复 ``detect_scenes → sample_frames → subcap`` 三步
boilerplate；多 fixture × 多 subcap 时反复 detect/sample 浪费严重。

Phase1AContext 把"待抽取的样本 + 已计算的 scenes/frames + 默认 client"打包成
一个 lazy 上下文：第一次 ``await ctx.scenes()`` 才跑 PySceneDetect；第一次
``await ctx.frames()`` 才跑 ffmpeg 抽帧。后续子能力调用共享同一份缓存。

子能力签名统一收口为 ``async def detect_X(ctx: Phase1AContext, *,
parent_event_id=None) -> tuple[Result, list[VisionEvent]]``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.extract.frame_sampler import FrameSample
    from app.extract.scenes import Scene
    from app.llm.client import LLMClient


@dataclass
class Phase1AContext:
    """Lazy 上下文：sample 路径 + task_id + scenes/frames 缓存。"""

    sample_id: str
    normalized_path: Path
    task_id: str
    _scenes: list[Scene] | None = field(default=None, repr=False)
    _frames: list[FrameSample] | None = field(default=None, repr=False)

    async def scenes(self) -> list[Scene]:
        """首次调用跑 PySceneDetect；后续返回缓存。

        把 ``frames_dir_rel`` 传给 ``detect_scenes`` 让它给每个 scene 写一张
        代表帧到与 frame_sampler 共享的目录——切点事件的 ``frame_url`` 因此
        直接可用，工作台左栏 D19 帧底图渲染条件得到满足。
        """
        if self._scenes is None:
            from app.extract.scenes import detect_scenes

            self._scenes, _ = await detect_scenes(
                self.normalized_path,
                task_id=self.task_id,
                frames_dir_rel=f"samples/{self.sample_id}/extracted/frames",
            )
        return self._scenes

    async def frames(self) -> list[FrameSample]:
        """首次调用跑 ffmpeg 抽帧（依赖 scenes）；后续返回缓存。"""
        if self._frames is None:
            from app.extract.frame_sampler import sample_frames

            scenes = await self.scenes()
            out_dir_rel = f"samples/{self.sample_id}/extracted/frames"
            self._frames, _ = await sample_frames(
                self.normalized_path,
                out_dir_rel=out_dir_rel,
                task_id=self.task_id,
                scenes=scenes,
            )
        return self._frames

    def client(self, stage: str) -> LLMClient:
        """按 stage 路由到 LLM provider（mixed 模式按前缀匹配）。"""
        from app.llm.client import get_llm_client

        return get_llm_client(stage=stage)

    @classmethod
    def from_sample_id(cls, sample_id: str, task_id: str) -> Phase1AContext:
        """便捷构造：从 ``data/samples/{sid}/`` 找 normalized.mp4 / source.mp4。"""
        from app.config import get_settings

        s = get_settings()
        sample_dir = s.data_root / "samples" / sample_id
        normalized = sample_dir / "normalized.mp4"
        if not normalized.exists():
            normalized = sample_dir / "source.mp4"
        return cls(sample_id=sample_id, normalized_path=normalized, task_id=task_id)
