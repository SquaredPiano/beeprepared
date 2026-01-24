import { create } from "zustand";
import { 
  Node, 
  Edge, 
  OnNodesChange, 
  OnEdgesChange, 
  OnConnect, 
  applyNodeChanges, 
  applyEdgeChanges, 
  addEdge,
  Connection,
  MarkerType,
  Viewport
} from "@xyflow/react";
import { supabase } from "@/lib/supabase";
import { toast } from "sonner";
import { generateProjectName } from "@/lib/utils/naming";

interface CanvasState {
  nodes: Node[];
  edges: Edge[];
  currentProjectId: string | null;
  projectName: string;
  isSaving: boolean;
  isDragging: boolean;
  isLocked: boolean;
  showMiniMap: boolean;
  isHeaderCollapsed: boolean;
  isSidebarCollapsed: boolean;
  viewport: Viewport;
  
  history: { nodes: Node[]; edges: Edge[] }[];
  historyIndex: number;
  
  // Actions
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  setIsDragging: (val: boolean) => void;
  setIsLocked: (val: boolean) => void;
  setShowMiniMap: (val: boolean) => void;
  setIsHeaderCollapsed: (val: boolean) => void;
  setIsSidebarCollapsed: (val: boolean) => void;
  setViewport: (viewport: Viewport) => void;
  setProjectName: (name: string) => void;
  
  undo: () => void;
  redo: () => void;
  takeSnapshot: () => void;
  
  save: () => Promise<void>;
  loadProject: (id: string) => Promise<void>;
  createNewProject: () => void;
}

export const useCanvasStore = create<CanvasState>((set, get) => ({
  nodes: [],
  edges: [],
  currentProjectId: null,
  projectName: generateProjectName(),
  isSaving: false,
  isDragging: false,
  isLocked: false,
  showMiniMap: true,
  isHeaderCollapsed: false,
  isSidebarCollapsed: false,
  viewport: { x: 0, y: 0, zoom: 1 },
  
  history: [],
  historyIndex: -1,

  takeSnapshot: () => {
    const { nodes, edges, history, historyIndex } = get();
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push({ 
      nodes: JSON.parse(JSON.stringify(nodes)), 
      edges: JSON.parse(JSON.stringify(edges)) 
    });
    
    if (newHistory.length > 200) newHistory.shift();
    
    set({ 
      history: newHistory, 
      historyIndex: newHistory.length - 1 
    });
  },

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),
  setIsDragging: (isDragging) => set({ isDragging }),
  setIsLocked: (isLocked) => set({ isLocked }),
  setShowMiniMap: (showMiniMap) => set({ showMiniMap }),
  setIsHeaderCollapsed: (isHeaderCollapsed) => set({ isHeaderCollapsed }),
  setIsSidebarCollapsed: (isSidebarCollapsed) => set({ isSidebarCollapsed }),
  setViewport: (viewport) => set({ viewport }),
  setProjectName: (projectName) => set({ projectName }),

  onNodesChange: (changes) => {
    if (get().isLocked) return;
    set({
      nodes: applyNodeChanges(changes, get().nodes),
    });
  },

  onEdgesChange: (changes) => {
    if (get().isLocked) return;
    set({
      edges: applyEdgeChanges(changes, get().edges),
    });
  },

  onConnect: (connection: Connection) => {
    if (get().isLocked) return;
    set({
      edges: addEdge({
        ...connection,
        animated: true,
        markerEnd: { 
          type: MarkerType.ArrowClosed, 
          color: "#FCD34F",
        },
        style: { 
          stroke: "#FCD34F", 
          strokeWidth: 2,
          strokeDasharray: "5 5",
        }
      }, get().edges),
    });
    get().takeSnapshot();
  },

  undo: () => {
    const { history, historyIndex } = get();
    if (historyIndex > 0) {
      const prev = history[historyIndex - 1];
      set({
        nodes: JSON.parse(JSON.stringify(prev.nodes)),
        edges: JSON.parse(JSON.stringify(prev.edges)),
        historyIndex: historyIndex - 1,
      });
    }
  },

  redo: () => {
    const { history, historyIndex } = get();
    if (historyIndex < history.length - 1) {
      const next = history[historyIndex + 1];
      set({
        nodes: JSON.parse(JSON.stringify(next.nodes)),
        edges: JSON.parse(JSON.stringify(next.edges)),
        historyIndex: historyIndex + 1,
      });
    }
  },

  save: async () => {
    const { nodes, edges, currentProjectId, projectName, viewport } = get();
    set({ isSaving: true });

    try {
      const { data: userData } = await supabase.auth.getUser();
      
      const projectData = {
        name: projectName,
        nodes,
        edges,
        viewport,
        user_id: userData.user?.id || null,
        updated_at: new Date().toISOString(),
      };

      let result;
      if (currentProjectId) {
        result = await supabase
          .from("projects")
          .update(projectData)
          .eq("id", currentProjectId)
          .select()
          .single();
      } else {
        result = await supabase
          .from("projects")
          .insert({ ...projectData, name: projectName || generateProjectName() })
          .select()
          .single();
      }

      if (result.error) throw result.error;

      set({ currentProjectId: result.data.id });
      toast.success("Architecture persisted to Hive");
    } catch (error: any) {
      console.error("Save error:", error);
      toast.error(`Failed to save: ${error.message}`);
    } finally {
      set({ isSaving: false });
    }
  },

  loadProject: async (id: string) => {
    try {
      const { data, error } = await supabase
        .from("projects")
        .select("*")
        .eq("id", id)
        .single();

      if (error) throw error;

      set({
        nodes: data.nodes || [],
        edges: data.edges || [],
        currentProjectId: data.id,
        projectName: data.name,
        viewport: data.viewport || { x: 0, y: 0, zoom: 1 },
        history: [],
        historyIndex: -1,
      });
      
      get().takeSnapshot();
    } catch (error: any) {
      toast.error(`Failed to load project: ${error.message}`);
    }
  },

  createNewProject: () => {
    set({
      nodes: [],
      edges: [],
      currentProjectId: null,
      projectName: generateProjectName(),
      viewport: { x: 0, y: 0, zoom: 1 },
      history: [],
      historyIndex: -1,
    });
    get().takeSnapshot();
  },
}));
