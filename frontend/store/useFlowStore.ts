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
  MarkerType
} from "@xyflow/react";
import { supabase } from "@/lib/supabase";
import { toast } from "sonner";

interface FlowState {
  nodes: Node[];
  edges: Edge[];
  currentProjectId: string | null;
  projectName: string;
  isSaving: boolean;
  history: { nodes: Node[]; edges: Edge[] }[];
  historyIndex: number;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  undo: () => void;
  redo: () => void;
  save: () => Promise<void>;
  loadProject: (id: string) => Promise<void>;
  createNewProject: () => void;
  resetView: () => void;
  takeSnapshot: () => void;
}

export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  currentProjectId: null,
  projectName: "Untitled Pipeline",
  isSaving: false,
  history: [],
  historyIndex: -1,

  takeSnapshot: () => {
    const { nodes, edges, history, historyIndex } = get();
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push({ 
      nodes: JSON.parse(JSON.stringify(nodes)), 
      edges: JSON.parse(JSON.stringify(edges)) 
    });
    
    // Limit history to 200 steps
    if (newHistory.length > 200) newHistory.shift();
    
    set({ 
      history: newHistory, 
      historyIndex: newHistory.length - 1 
    });
  },

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  onNodesChange: (changes) => {
    set({
      nodes: applyNodeChanges(changes, get().nodes),
    });
  },

  onEdgesChange: (changes) => {
    set({
      edges: applyEdgeChanges(changes, get().edges),
    });
  },

  onConnect: (connection: Connection) => {
    set({
      edges: addEdge({
        ...connection,
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" },
        style: { stroke: "#FCD34F", strokeWidth: 2 }
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
    const { nodes, edges, currentProjectId, projectName } = get();
    set({ isSaving: true });

    try {
      const { data: userData } = await supabase.auth.getUser();
      
      const projectData = {
        name: projectName,
        nodes,
        edges,
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
          .insert({ ...projectData, name: projectName || "Untitled Pipeline" })
          .select()
          .single();
      }

      if (result.error) throw result.error;

      set({ currentProjectId: result.data.id });
      toast.success("Pipeline saved successfully");
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
        nodes: data.nodes,
        edges: data.edges,
        currentProjectId: data.id,
        projectName: data.name,
        history: [],
        historyIndex: -1,
      });
      
      get().takeSnapshot();
      toast.success("Project loaded");
    } catch (error: any) {
      toast.error(`Failed to load project: ${error.message}`);
    }
  },

  createNewProject: () => {
    set({
      nodes: [],
      edges: [],
      currentProjectId: null,
      projectName: "Untitled Pipeline",
      history: [],
      historyIndex: -1,
    });
    get().takeSnapshot();
  },

  resetView: () => {
    // Handled by component
  },
}));
