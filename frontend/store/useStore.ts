import { create } from "zustand";

interface FileState {
  id: string;
  name: string;
  status: "pending" | "uploading" | "processing" | "completed" | "error";
  progress: number;
}

interface AppState {
  files: FileState[];
  isProcessing: boolean;
  addFile: (name: string) => string;
  updateFileStatus: (id: string, status: FileState["status"]) => void;
  updateFileProgress: (id: string, progress: number) => void;
  setProcessing: (val: boolean) => void;
}

export const useStore = create<AppState>((set) => ({
  files: [],
  isProcessing: false,
  addFile: (name) => {
    const id = Math.random().toString(36).substring(7);
    set((state) => ({
      files: [
        ...state.files,
        { id, name, status: "pending", progress: 0 },
      ],
    }));
    return id;
  },
  updateFileStatus: (id, status) =>
    set((state) => ({
      files: state.files.map((f) => (f.id === id ? { ...f, status } : f)),
    })),
  updateFileProgress: (id, progress) =>
    set((state) => ({
      files: state.files.map((f) => (f.id === id ? { ...f, progress } : f)),
    })),
  setProcessing: (val) => set({ isProcessing: val }),
}));
