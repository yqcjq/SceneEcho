import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  applyTemplate,
  dataUrl,
  getPreviewProps,
  getProject,
  PreviewProps,
  ProjectResponse,
  recommendTemplates,
  RecommendItem,
  renderProject,
  uploadProject,
} from "../api/index.js";
import { RemotionPlayer } from "../components/RemotionPlayer.js";
import { TaskProgress } from "../components/TaskProgress.js";

/**
 * Phase 2 · ★MVP closed loop (PLAN 1636-1650).
 *
 * Flow:
 *  1. upload user material (≤20s 口播)        → POST /projects
 *  2. fetch top-3 template recommendations    → POST /projects/{id}/recommend-templates
 *  3. pick a template, click "应用"            → POST /projects/{id}/apply  (background)
 *  4. live-preview the ProjectIR              → GET  /projects/{id}/preview-props
 *  5. click "渲染出片" → MP4                  → POST /projects/{id}/render  → poll task
 *
 * Each stage shows progress via ``TaskProgress`` + a workbench link so the
 * user can drop into ``/workbench/{task_id}`` for the AI decision stream.
 */
export const Editor: React.FC = () => {
  const { projectId: paramProjectId } = useParams<{ projectId?: string }>();
  const navigate = useNavigate();
  const [projectId, setProjectId] = useState<string | null>(paramProjectId ?? null);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [recs, setRecs] = useState<RecommendItem[] | null>(null);
  const [recsLoading, setRecsLoading] = useState(false);
  const [recsTaskId, setRecsTaskId] = useState<string | null>(null);
  const [chosenTemplate, setChosenTemplate] = useState<string | null>(null);
  const [applyTaskId, setApplyTaskId] = useState<string | null>(null);
  const [renderTaskId, setRenderTaskId] = useState<string | null>(null);
  const [renderedPath, setRenderedPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewProps | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!projectId) return;
    void (async () => {
      try {
        const p = await getProject(projectId);
        setProject(p);
        if (p.ir) {
          try {
            setPreview(await getPreviewProps(projectId));
          } catch {
            /* ignore — apply not run yet */
          }
        }
      } catch {
        /* project not found yet */
      }
    })();
  }, [projectId]);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    setBusy(true);
    try {
      const r = await uploadProject(file);
      setProjectId(r.project_id);
      navigate(`/editor/${r.project_id}`, { replace: true });
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    } finally {
      setBusy(false);
    }
  };

  const onRecommend = async () => {
    if (!projectId) return;
    setError(null);
    setRecsLoading(true);
    try {
      const r = await recommendTemplates(projectId, 3);
      setRecs(r.recommendations);
      setRecsTaskId(r.task_id);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    } finally {
      setRecsLoading(false);
    }
  };

  const onApply = async (templateId: string) => {
    if (!projectId) return;
    setError(null);
    setChosenTemplate(templateId);
    setRenderedPath(null);
    setRenderTaskId(null);
    try {
      const r = await applyTemplate(projectId, templateId);
      setApplyTaskId(r.task_id);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  };

  const onRender = async () => {
    if (!projectId) return;
    setError(null);
    setRenderedPath(null);
    try {
      const r = await renderProject(projectId);
      setRenderTaskId(r.task_id);
    } catch (err: any) {
      setError(String(err?.response?.data?.detail ?? err?.message ?? err));
    }
  };

  return (
    <div className="mx-auto max-w-[1180px] px-6 py-8" style={{ fontFamily: "system-ui, sans-serif" }}>
      <h1 className="font-serif text-2xl">SceneEcho · 阶段 2 出片</h1>
      <p className="text-secondary text-sm mt-1">
        上传 10–20s 一镜到底口播 → VLM 推荐模板 → 应用 → 实时预览 → 渲染 MP4 直接下载。
      </p>

      <section className="mt-6">
        <label className="block text-sm font-medium mb-1">1. 上传用户素材</label>
        <input
          type="file"
          accept="video/mp4,video/quicktime,video/webm"
          onChange={onUpload}
          disabled={busy}
        />
        {busy && <span className="ml-3 text-secondary text-sm">归一化中…</span>}
        {projectId && (
          <div className="mt-2 text-sm">
            project_id: <code className="text-secondary">{projectId}</code>
            {project?.user_material_url ? (
              <video
                src={project.user_material_url}
                controls
                style={{ width: 240, marginTop: 8, borderRadius: 4 }}
              />
            ) : null}
          </div>
        )}
      </section>

      {projectId && (
        <section className="mt-8">
          <div className="flex items-baseline justify-between">
            <label className="text-sm font-medium">2. 模板推荐</label>
            <button
              type="button"
              className="text-sm text-accent-primary hover:underline disabled:text-tertiary"
              onClick={onRecommend}
              disabled={recsLoading}
            >
              {recsLoading ? "推荐中…" : recs ? "重新推荐" : "调 VLM 推荐 top-3"}
            </button>
          </div>
          {recsTaskId && (
            <div className="mt-2 text-xs text-secondary">
              推荐推理事件流：
              <Link to={`/workbench/${recsTaskId}`} className="ml-1 text-accent-primary hover:underline">
                打开 AI 工作台 #{recsTaskId.slice(0, 8)}
              </Link>
            </div>
          )}
          <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
            {(recs ?? []).map((rec) => {
              const isChosen = chosenTemplate === rec.template_id;
              return (
                <button
                  key={rec.template_id}
                  type="button"
                  className={`rounded-md border p-3 text-left transition ${
                    isChosen
                      ? "border-accent-primary bg-accent-subtle"
                      : "border-border bg-surface hover:border-accent-primary"
                  }`}
                  onClick={() => onApply(rec.template_id)}
                  disabled={!!applyTaskId && !renderedPath}
                >
                  <div className="flex items-baseline gap-2">
                    <span className="font-serif text-base">{rec.name ?? rec.template_id}</span>
                    <span className="text-tertiary text-xs">{rec.score.toFixed(2)}</span>
                  </div>
                  {rec.thumbnail_path ? (
                    <img
                      src={dataUrl(rec.thumbnail_path)}
                      alt=""
                      style={{ width: "100%", marginTop: 6, borderRadius: 4 }}
                    />
                  ) : null}
                  <p className="mt-2 text-secondary text-sm whitespace-pre-wrap leading-snug">
                    {rec.reason}
                  </p>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {applyTaskId && (
        <section className="mt-6">
          <label className="text-sm font-medium">3. apply pipeline</label>
          <TaskProgress
            taskId={applyTaskId}
            onComplete={async (t) => {
              if (t.status === "completed" && projectId) {
                try {
                  setPreview(await getPreviewProps(projectId));
                  setProject(await getProject(projectId));
                } catch (err: any) {
                  setError(String(err?.message ?? err));
                }
              } else if (t.status === "failed") {
                setError(t.error ?? "apply failed");
              }
            }}
          />
          <Link
            to={`/workbench/${applyTaskId}`}
            className="text-sm text-accent-primary hover:underline"
          >
            打开 AI 工作台 #{applyTaskId.slice(0, 8)} 看 apply 全链路
          </Link>
        </section>
      )}

      {preview && (
        <section className="mt-8 grid grid-cols-1 gap-6 md:grid-cols-[auto_1fr]">
          <div>
            <label className="text-sm font-medium block mb-2">4. 实时预览</label>
            <RemotionPlayer
              canvas={preview.canvas}
              segments={preview.sections[0]?.segments ?? []}
              captions={preview.captions ?? []}
              userMaterialUrl={preview.user_material_url}
              bgmUrl={preview.bgm_url}
              displayWidth={360}
            />
          </div>
          <div>
            <label className="text-sm font-medium">ProjectIR 概览</label>
            <ul className="mt-2 text-sm text-secondary space-y-1">
              <li>段数：{preview.sections[0]?.segments?.length ?? 0}</li>
              <li>字幕：{preview.captions?.length ?? 0} 条</li>
              <li>BGM：{preview.bgm_url ? "✅" : "—"}</li>
              <li>canvas: {preview.canvas.width}×{preview.canvas.height}@{preview.canvas.fps}</li>
            </ul>
            <div className="mt-4">
              <button
                type="button"
                className="rounded-md bg-accent-primary px-4 py-2 text-inverted hover:bg-accent-hover"
                onClick={onRender}
                disabled={!!renderTaskId && !renderedPath}
              >
                {renderTaskId && !renderedPath ? "渲染中…" : "渲染出片"}
              </button>
            </div>
          </div>
        </section>
      )}

      {renderTaskId && (
        <section className="mt-6">
          <label className="text-sm font-medium">5. 渲染出片</label>
          <TaskProgress
            taskId={renderTaskId}
            onComplete={(t) => {
              if (t.status === "completed" && t.result?.output_path) {
                setRenderedPath(t.result.output_path);
              } else if (t.status === "failed") {
                setError(t.error ?? "render failed");
              }
            }}
          />
        </section>
      )}

      {renderedPath && (
        <section className="mt-6">
          <div className="text-sm">
            输出：<code className="text-secondary">{renderedPath}</code>
          </div>
          <video
            src={dataUrl(renderedPath)}
            controls
            style={{ width: 360, marginTop: 8, borderRadius: 4 }}
          />
          <div className="mt-2">
            <a
              href={dataUrl(renderedPath)}
              download
              className="text-sm text-accent-primary hover:underline"
            >
              下载 MP4
            </a>
          </div>
        </section>
      )}

      {error && <div className="text-error mt-6 text-sm">错误：{error}</div>}
    </div>
  );
};
