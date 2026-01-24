import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface QueueTask {
  id: string;
  lectureId: string;
  artifactType: 'notes' | 'flashcards' | 'exam' | 'audio';
  createdAt: number;
  status: 'pending' | 'processing' | 'complete' | 'failed';
  progress: number;
  stage?: string;
}

interface QueueStore {
  tasks: QueueTask[];
  addTask: (task: QueueTask) => void;
  updateTask: (id: string, updates: Partial<QueueTask>) => void;
  removeTask: (id: string) => void;
}

export const useQueueStore = create<QueueStore>()(
  persist(
    (set) => ({
      tasks: [],
      addTask: (task) => set((state) => ({ 
        tasks: [task, ...state.tasks] 
      })),
      updateTask: (id, updates) => set((state) => ({
        tasks: state.tasks.map((t) => t.id === id ? { ...t, ...updates } : t)
      })),
      removeTask: (id) => set((state) => ({ 
        tasks: state.tasks.filter(t => t.id !== id) 
      })),
    }),
    { name: 'bee-queue' }
  )
);
