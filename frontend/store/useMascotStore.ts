import { create } from 'zustand';

type MascotMood = 'idle' | 'happy' | 'thinking' | 'celebrating' | 'hidden';
type MascotPosition = 'bottom-right' | 'center' | 'top-right' | 'hidden';

interface MascotState {
  mood: MascotMood;
  position: MascotPosition;
  message: string | null;
  
  // Actions
  setMood: (mood: MascotMood) => void;
  say: (message: string, duration?: number) => void;
  flyTo: (position: MascotPosition) => void;
  celebrate: (message: string) => void;
  reset: () => void;
}

export const useMascotStore = create<MascotState>((set, get) => ({
  mood: 'hidden',
  position: 'hidden',
  message: null,

  setMood: (mood) => set({ mood }),
  
  flyTo: (position) => set({ position }),

  say: (message, duration = 4000) => {
    set({ message, mood: 'idle' });
    if (duration > 0) {
      setTimeout(() => {
        set((state) => (state.message === message ? { message: null } : {}));
      }, duration);
    }
  },

  celebrate: (message) => {
    const prevPosition = get().position;
    set({ position: 'center', mood: 'celebrating', message });
    
    setTimeout(() => {
      set({ position: prevPosition, mood: 'idle', message: null });
    }, 3500);
  },

  reset: () => set({ mood: 'idle', position: 'bottom-right', message: null }),
}));
