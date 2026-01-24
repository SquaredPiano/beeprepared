import { create } from "zustand";

interface SidebarState {
  isCollapsed: boolean;
  toggle: () => void;
  setCollapsed: (val: boolean) => void;
}

export const useSidebarStore = create<SidebarState>((set) => ({
  isCollapsed: false,
  toggle: () => set((state) => ({ isCollapsed: !state.isCollapsed })),
  setCollapsed: (val) => set({ isCollapsed: val }),
}));
