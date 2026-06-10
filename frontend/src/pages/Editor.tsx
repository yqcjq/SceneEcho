import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  applyTemplate,
  dataUrl,
  type EditResponse,
  getPreviewProps,
  getProject,
  getRecommendations,
  listProjectTasks,
  PreviewProps,
  ProjectResponse,
  recommendTemplates,
  RecommendItem,
  renderProject,
  uploadProject,
} from "../api/index.js";
import { NLBar } from "../components/editor/NLBar.js";
import { ParamPanel } from "../components/editor/ParamPanel.js";
import { PatchHistoryList } from "../components/editor/PatchHistoryList.js";
import { ProjectHistoryStrip } from "../components/editor/ProjectHistoryStrip.js";
import { StepCard } from "../components/editor/StepCard.js";
import { RemotionPlayer } from "../components/RemotionPlayer.js";
import { TaskProgress } from "../components/TaskProgress.js";

/**
 * Phase 2 · ★MVP closed loop (PLAN 1636-1650) with Phase 2.5 二核 polish.
 *
 * Flow:
 *  1. upload user material (≤20s 口播)        → POST /projects
 *  2. fetch top-3 template recommendations    → POST /projects/{id}/recommend-templates
 *  3. pick a template, click "应用"            → POST /projects/{id}/apply  (background)
 *  4. live-preview + ParamPanel + NLBar + PatchHistoryList (three-pane)
 *  5. click "渲染出片" → MP4                  → POST /projects/{id}/render  → poll task
 *
 * Each step is a ``StepCard`` so the page reads as a guided document
 * rather than naked sections. The fixed-height three-pane editor (Step 4)
 * keeps the preview column stable no matter how long the patch history
 * grows — see Phase 2.5 二核 plan for the height-isolation root cause.
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
  const [applyDone, setApplyDone] = useState(false);
  const [renderTaskId, setRenderTaskId] = useState<string | null>(null);
  const [renderedPath, setRenderedPath] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewProps | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Phase 2.5: tick whenever an edit / undo lands so the right pane reloads.
  const [editTick, setEditTick] = useState(0);

  // Re-sync local state when the URL changes (history strip click).
  useEffect(() => {
    setProjectId(paramProjectId ?? null);
    setProject(null);
    setPreview(null);
    setRecs(null);
    setRecsTaskId(null);
    setChosenTemplate(null);
    setApplyTaskId(null);
    setApplyDone(false);
    setRenderTaskId(null);
    setRenderedPath(null);
    setEditTick(0);
  }, [paramProjectId]);

  const refreshPreview = React.useCallback(async (pid: string) => {
    try {
      const next = await getPreviewProps(pid);
      setPreview(next);
    } catch {
      /* ignore — apply not run yet */
    }
  }, []);

  const handleEditApplied = React.useCallback(
    (r: EditResponse) => {
      if (!projectId) return;
      // Background render is already kicked off via render_task_id; the
      // editor just needs the new preview-props so the player updates.
      setRenderTaskId(r.render_task_id);
      setRenderedPath(null);
      setEditTick((n) => n + 1);
      void refreshPreview(projectId);
    },
    [projectId, refreshPreview],
  );

  useEffect(() => {
    if (!projectId) return;
    // Cancel-on-unmount flag (ISS-026): when the user clicks ProjectHistoryStrip
    // rapidly, multiple effect runs can have in-flight HTTP responses; the
    // older one resolving last would clobber the newer project's state with
    // stale data. We check ``cancelled`` after every await boundary so a
    // teardown cuts off all four state writes — both the parallel triple
    // and the inner getPreviewProps await.
    let cancelled = false;
    void (async () => {
      // Restore prior step-2/step-3 UI state from the backend's persisted
      // truth sources (D36): project.json + tasks table + events.jsonl.
      // The three reads are independent so we run them in parallel and
      // tolerate any subset being missing — a fresh project simply renders
      // empty cards as if none were touched yet.
      const [projectRes, recsRes, tasksRes] = await Promise.allSettled([
        getProject(projectId),
        getRecommendations(projectId),
        listProjectTasks(projectId),
      ]);
      if (cancelled) return;

      if (projectRes.status === "fulfilled") {
        const p = projectRes.value;
        setProject(p);
        if (p.ir) {
          setApplyDone(true);
          // Pull the chosen template id straight from the persisted
          // ProjectIR — apply_short locked it into sections[0].template_id,
          // so the step-2 card can highlight which recommendation got picked.
          const chosen = (p.ir as { sections?: Array<{ template_id?: string }> })
            ?.sections?.[0]?.template_id;
          if (chosen) setChosenTemplate(chosen);
          try {
            const next = await getPreviewProps(projectId);
            if (cancelled) return;
            setPreview(next);
          } catch {
            /* preview-props 404s when apply ran but degraded — keep going */
          }
        }
      }

      if (recsRes.status === "fulfilled") {
        const r = recsRes.value;
        // Recover the workbench link whenever a recommend task exists, even
        // if it produced zero entity events (failed mid-flight) — the user
        // still needs an entry into /workbench/{task_id} to debug. Cards
        // only render when there's something to show.
        if (r.task_id) setRecsTaskId(r.task_id);
        if (r.recommendations.length > 0) setRecs(r.recommendations);
      }

      if (tasksRes.status === "fulfilled") {
        // list_by_resource returns DESC by created_at, so .find picks the
        // latest apply_short — the one that produced the current
        // project.json. Step-3's workbench link recovers from this id.
        const apply = tasksRes.value.tasks.find((t) => t.kind === "apply_short");
        if (apply) setApplyTaskId(apply.task_id);
      }
    })();
    return () => {
      cancelled = true;
    };
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
    setApplyDone(false);
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

  // Status derivation for each step — drives the StepCard badge color.
  const step1Status = projectId ? "done" : "active";
  const step2Status = !projectId
    ? "pending"
    : recs
    ? chosenTemplate
      ? "done"
      : "active"
    : "active";
  const step3Status = applyDone ? "done" : !applyTaskId ? "pending" : "active";
  const step4Status = !preview ? "pending" : "active";
  const step5Status = !renderTaskId
    ? "pending"
    : renderedPath
    ? "done"
    : "active";

  return (
    <div className="mx-auto max-w-[1180px] px-6 py-12" style={{ fontFamily: "system-ui, sans-serif" }}>
      <header className="mb-8">
        <h1 className="font-serif text-2xl">SceneEcho · 阶段 2 出片</h1>
        <p className="text-secondary text-sm mt-1">
          上传 10–20s 一镜到底口播 → VLM 推荐模板 → 应用 → 实时预览 → 渲染 MP4 直接下载。
        </p>
      </header>

      <div className="space-y-6">
        <ProjectHistoryStrip currentProjectId={projectId} />

        <StepCard
          step={1}
          title="上传用户素材"
          status={step1Status}
          meta={projectId ? <code className="font-mono">{projectId}</code> : null}
        >
          <input
            type="file"
            accept="video/mp4,video/quicktime,video/webm"
            onChange={onUpload}
            disabled={busy}
          />
          {busy && <span className="ml-3 text-secondary text-sm">归一化中…</span>}
          {project?.user_material_url && (
            <div className="mt-3">
              <video
                src={project.user_material_url}
                controls
                style={{ width: 240, borderRadius: 4 }}
              />
            </div>
          )}
        </StepCard>

        {projectId && (
          <StepCard
            step={2}
            title="模板推荐"
            status={step2Status}
            meta={
              recsTaskId ? (
                <Link
                  to={`/workbench/${recsTaskId}`}
                  className="text-accent-primary hover:underline"
                >
                  推荐推理 #{recsTaskId.slice(0, 8)} →
                </Link>
              ) : null
            }
          >
            <div className="flex items-center justify-between">
              <p className="text-secondary text-sm">
                VLM 综合 ASR 摘要 + 关键帧从模板库中 top-3 排序，点击卡片即应用。
              </p>
              <button
                type="button"
                className="text-sm text-accent-primary hover:underline disabled:text-tertiary"
                onClick={onRecommend}
                disabled={recsLoading}
              >
                {recsLoading ? "推荐中…" : recs ? "重新推荐" : "调 VLM 推荐 top-3"}
              </button>
            </div>
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
                        : "border-border bg-canvas hover:border-accent-primary"
                    }`}
                    onClick={() => onApply(rec.template_id)}
                    disabled={!!applyTaskId && !applyDone}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="font-serif text-base">{rec.name ?? rec.template_id}</span>
                      <span className="text-tertiary text-xs">{rec.score.toFixed(2)}</span>
                    </div>
                    {rec.thumbnail_path ? (
                      <img
                        src={dataUrl(rec.thumbnail_path)}
                        alt=""
                        style={{ width: "100%", maxHeight: 80, objectFit: "cover", marginTop: 6, borderRadius: 4 }}
                      />
                    ) : null}
                    <p className="mt-2 text-secondary text-sm whitespace-pre-wrap leading-snug">
                      {rec.reason}
                    </p>
                  </button>
                );
              })}
            </div>
          </StepCard>
        )}

        {(applyTaskId || applyDone) && (
          <StepCard
            step={3}
            title="apply pipeline"
            status={step3Status}
            meta={
              applyTaskId ? (
                <Link
                  to={`/workbench/${applyTaskId}`}
                  className="text-accent-primary hover:underline"
                >
                  apply 全链路 #{applyTaskId.slice(0, 8)} →
                </Link>
              ) : null
            }
          >
            {applyTaskId ? (
              <TaskProgress
                taskId={applyTaskId}
                onComplete={async (t) => {
                  if (t.status === "completed" && projectId) {
                    try {
                      setPreview(await getPreviewProps(projectId));
                      setProject(await getProject(projectId));
                      setApplyDone(true);
                    } catch (err: any) {
                      setError(String(err?.message ?? err));
                    }
                  } else if (t.status === "failed") {
                    setError(t.error ?? "apply failed");
                  }
                }}
              />
            ) : (
              <p className="text-sm text-secondary">已从历史记录加载，apply pipeline 已完成。</p>
            )}
          </StepCard>
        )}

        {preview && (
          <StepCard
            step={4}
            title="实时预览 + 编辑"
            status={step4Status}
            meta={
              <span>
                v{(project?.ir as any)?.version ?? 1} · {preview.sections[0]?.segments?.length ?? 0} 段 ·{" "}
                {preview.captions?.length ?? 0} 字幕
              </span>
            }
          >
            <div className="grid h-[910px] grid-cols-1 gap-0 overflow-hidden rounded-md border border-border md:grid-cols-[18rem_1fr_20rem]">
              <ParamPanel
                projectId={projectId!}
                ir={project?.ir}
                onApplied={handleEditApplied}
              />
              <div className="flex h-full flex-col overflow-hidden">
                <div className="flex-1 flex flex-col items-center px-4 py-4">
                  <RemotionPlayer
                    canvas={preview.canvas}
                    segments={preview.sections[0]?.segments ?? []}
                    captions={preview.captions ?? []}
                    userMaterialUrl={preview.user_material_url}
                    bgmUrl={preview.bgm_url}
                    displayWidth={300}
                  />
                  <ul className="mt-4 w-full text-sm text-secondary space-y-1">
                    <li>段数：{preview.sections[0]?.segments?.length ?? 0}</li>
                    <li>字幕：{preview.captions?.length ?? 0} 条</li>
                    <li>BGM：{preview.bgm_url ? "✅" : "—"}</li>
                    <li>
                      canvas: {preview.canvas.width}×{preview.canvas.height}@
                      {preview.canvas.fps}
                    </li>
                  </ul>
                </div>
                <NLBar
                  projectId={projectId!}
                  onSent={handleEditApplied}
                  disabled={!project?.ir}
                />
              </div>
              <PatchHistoryList
                projectId={projectId!}
                refreshKey={editTick}
                onUndone={handleEditApplied}
                applyTaskId={applyTaskId}
              />
            </div>
            <div className="mt-4 flex items-center justify-between gap-3 rounded-md border border-border bg-surface px-5 py-3">
              <span className="text-sm text-secondary">
                编辑完成，点击右侧按钮触发渲染。
              </span>
              <button
                type="button"
                onClick={onRender}
                disabled={!!renderTaskId && !renderedPath}
                className="rounded-md bg-accent-subtle px-5 py-2 text-sm font-medium text-accent-primary disabled:opacity-50"
              >
                {renderTaskId && !renderedPath ? "渲染中…" : "渲染出片"}
              </button>
            </div>
          </StepCard>
        )}

        {renderTaskId && (
          <StepCard step={5} title="渲染出片" status={step5Status}>
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
            {renderedPath && (
              <div className="mt-4">
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
              </div>
            )}
          </StepCard>
        )}

        {error && (
          <div className="rounded-md border border-error bg-surface px-4 py-3 text-sm text-error">
            错误：{error}
          </div>
        )}
      </div>
    </div>
  );
};
