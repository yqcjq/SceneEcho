import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import "./styles/global.css";
import { Editor } from "./pages/Editor.js";
import { SampleExtract } from "./pages/SampleExtract.js";
import { SubcapabilityLab } from "./pages/SubcapabilityLab.js";
import { TemplateLibrary } from "./pages/TemplateLibrary.js";
import { Workbench } from "./pages/Workbench.js";
import { WorkbenchLauncher } from "./pages/WorkbenchLauncher.js";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");

const Shell: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="min-h-screen bg-canvas text-primary">
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex max-w-[1280px] items-center justify-between px-6 py-4">
        <div className="flex items-baseline gap-3">
          <span className="font-serif text-lg">SceneEcho</span>
          <span className="text-tertiary text-xs">口播视频「结构 + 风格」迁移</span>
        </div>
        <nav className="flex gap-6 text-sm text-secondary">
          <Link to="/sample-extract" className="hover:text-primary">样例</Link>
          <Link to="/templates" className="hover:text-primary">模板库</Link>
          <Link to="/editor" className="hover:text-primary">出片</Link>
          <Link to="/workbench/dev" className="hover:text-primary">工作台</Link>
          {import.meta.env.DEV && (
            <Link to="/lab" className="hover:text-primary">Lab</Link>
          )}
        </nav>
      </div>
    </header>
    <main>{children}</main>
  </div>
);

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/sample-extract" replace />} />
        <Route
          path="/sample-extract"
          element={
            <Shell>
              <SampleExtract />
            </Shell>
          }
        />
        <Route
          path="/workbench/dev"
          element={
            <Shell>
              <WorkbenchLauncher />
            </Shell>
          }
        />
        <Route
          path="/templates"
          element={
            <Shell>
              <TemplateLibrary />
            </Shell>
          }
        />
        <Route
          path="/templates/:id"
          element={
            <Shell>
              <TemplateLibrary />
            </Shell>
          }
        />
        <Route
          path="/editor"
          element={
            <Shell>
              <Editor />
            </Shell>
          }
        />
        <Route
          path="/editor/:projectId"
          element={
            <Shell>
              <Editor />
            </Shell>
          }
        />
        <Route
          path="/workbench/:taskId"
          element={
            <Shell>
              <Workbench />
            </Shell>
          }
        />
        {import.meta.env.DEV && (
          <Route
            path="/lab"
            element={
              <Shell>
                <SubcapabilityLab />
              </Shell>
            }
          />
        )}
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
