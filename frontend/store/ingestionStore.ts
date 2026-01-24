import { create } from 'zustand';

export interface Task {
  id: string;
  name: string;
  status: 'pending' | 'processing' | 'complete' | 'failed';
  progress: number;
  type: 'pdf' | 'audio' | 'video';
  timestamp: number;
}

interface IngestionState {
  tasks: Task[];
  addTask: (task: Task) => void;
  updateTask: (id: string, updates: Partial<Task>) => void;
  removeTask: (id: string) => void;
}

export const useIngestionStore = create<IngestionState>((set) => ({
  tasks: [],
  addTask: (task) => set((state) => ({ tasks: [task, ...state.tasks] })),
  updateTask: (id, updates) =>
    set((state) => ({
      tasks: state.tasks.map((t) => (t.id === id ? { ...t, ...updates } : t)),
    })),
  removeTask: (id) =>
    set((state) => ({
      tasks: state.tasks.filter((t) => t.id !== id),
    })),
}));
