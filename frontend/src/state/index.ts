import { create } from "zustand";
import type { TaskStatus } from "../api/index.js";

interface AppState {
  currentTask: TaskStatus | null;
  setTask: (t: TaskStatus | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  currentTask: null,
  setTask: (t) => set({ currentTask: t }),
}));
