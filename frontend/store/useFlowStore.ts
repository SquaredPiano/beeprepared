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

interface FlowState {
  nodes: Node[];
  edges: Edge[];
  history: { nodes: Node[]; edges: Edge[] }[];
  historyIndex: number;
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  undo: () => void;
  redo: () => void;
  save: () => void;
  resetView: () => void;
  takeSnapshot: () => void;
}

export const useFlowStore = create<FlowState>((set, get) => ({
  nodes: [],
  edges: [],
  history: [],
  historyIndex: -1,

  takeSnapshot: () => {
    const { nodes, edges, history, historyIndex } = get();
    const newHistory = history.slice(0, historyIndex + 1);
    newHistory.push({ 
      nodes: JSON.parse(JSON.stringify(nodes)), 
      edges: JSON.parse(JSON.stringify(edges)) 
    });
    
    // Limit history to 50 steps
    if (newHistory.length > 50) newHistory.shift();
    
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

  save: () => {
    const { nodes, edges } = get();
    const data = JSON.stringify({ nodes, edges }, null, 2);
    const blob = new Blob([data], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `beeprepared-flow-${new Date().toISOString()}.json`;
    link.click();
    URL.revokeObjectURL(url);
  },

  resetView: () => {
    // This is handled by useReactFlow in the component
  },
}));
