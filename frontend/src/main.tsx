import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { SampleExtract } from "./pages/SampleExtract.js";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/sample-extract" replace />} />
        <Route path="/sample-extract" element={<SampleExtract />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
