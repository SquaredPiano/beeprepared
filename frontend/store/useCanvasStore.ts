import { create } from "zustand";
import { persist } from "zustand/middleware";
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
import { api, Artifact, ArtifactEdge } from "@/lib/api";

// Maps artifact types to node display info
const ARTIFACT_TYPE_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  video: { label: "Video", color: "#8B5CF6", icon: "🎬" },
  audio: { label: "Audio", color: "#EC4899", icon: "🎵" },
  text: { label: "Raw Text", color: "#6B7280", icon: "📄" },
  flat_text: { label: "Cleaned Text", color: "#10B981", icon: "✨" },
  knowledge_core: { label: "Knowledge Core", color: "#F59E0B", icon: "🧠" },
  quiz: { label: "Quiz", color: "#3B82F6", icon: "❓" },
  flashcards: { label: "Flashcards", color: "#8B5CF6", icon: "🃏" },
  notes: { label: "Notes", color: "#10B981", icon: "📝" },
  slides: { label: "Slides", color: "#F97316", icon: "📊" },
  exam: { label: "Exam", color: "#EF4444", icon: "📋" },
};

// Convert an artifact to a React Flow node
function artifactToNode(artifact: Artifact, position: { x: number; y: number }): Node {
  const config = ARTIFACT_TYPE_CONFIG[artifact.type] || { label: artifact.type, color: "#6B7280", icon: "📦" };
  
  return {
    id: artifact.id,
    type: "artifactNode",
    position,
    data: {
      label: config.label,
      type: artifact.type,
      icon: config.icon,
      color: config.color,
      artifact,
      status: "completed",
    },
  };
}

// Convert an artifact edge to a React Flow edge
function artifactEdgeToFlowEdge(edge: ArtifactEdge): Edge {
  return {
    id: edge.id,
    source: edge.parent_artifact_id,
    target: edge.child_artifact_id,
    animated: true,
    markerEnd: { 
      type: MarkerType.ArrowClosed, 
      color: "#FCD34F",
    },
    style: { 
      stroke: "#FCD34F", 
      strokeWidth: 2,
    },
    data: {
      relationship: edge.relationship_type,
    },
  };
}

interface CanvasState {
  nodes: Node[];
  edges: Edge[];
  currentProjectId: string | null;
  projectName: string;
  isSaving: boolean;
  isUploading: boolean;
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
    runFlow: () => Promise<void>;
    loadProject: (id: string) => Promise<void>;
    createNewProject: () => void;
    uploadFile: (file: File) => Promise<void>;
    refreshArtifacts: () => Promise<void>;
  }
  
  export const useCanvasStore = create<CanvasState>()(
    persist(
      (set, get) => ({
        nodes: [],
        edges: [],
        currentProjectId: null,
        projectName: generateProjectName(),
        isSaving: false,
        isUploading: false,
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
          const { nodes, currentProjectId, projectName, viewport } = get();
          set({ isSaving: true });
  
          try {
            // Build node positions map for canvas_state
            const node_positions: Record<string, { x: number; y: number }> = {};
            nodes.forEach((node) => {
              node_positions[node.id] = { x: node.position.x, y: node.position.y };
            });
            
            const canvas_state = {
              viewport,
              node_positions,
            };
  
            if (currentProjectId) {
              // Update existing project
              await api.projects.update(currentProjectId, {
                name: projectName,
                canvas_state,
              });
            } else {
              // Create new project
              const project = await api.projects.create(projectName);
              set({ currentProjectId: project.id });
            }
  
            toast.success("Project saved");
          } catch (error: any) {
            console.error("Save error:", error);
            toast.error(`Failed to save: ${error.message}`);
          } finally {
            set({ isSaving: false });
          }
        },
  
        runFlow: async () => {
          const { nodes, edges, currentProjectId } = get();
          if (!currentProjectId) {
            toast.error("Save your project first");
            return;
          }
  
          toast.promise(async () => {
            const { data: { session } } = await supabase.auth.getSession();
            const response = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'}/run`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${session?.access_token}`
              },
              body: JSON.stringify({
                project_id: currentProjectId,
                nodes,
                edges
              })
            });
  
            if (!response.ok) {
              const err = await response.json();
              throw new Error(err.detail || "Pipeline execution failed");
            }
  
            return await response.json();
          }, {
            loading: 'Activating knowledge pipeline...',
            success: 'Pipeline activated. Check node status for progress.',
            error: (err) => err.message
          });
        },

      loadProject: async (id: string) => {
        try {
          // 1. Load project metadata
          const project = await api.projects.get(id);
          
          // 2. Load artifacts and edges from backend
          const { artifacts, edges: artifactEdges } = await api.projects.getArtifacts(id);
          
          // 3. Get node positions from canvas_state or auto-layout
          const nodePositions = project.canvas_state?.node_positions || {};
          
          // 4. Convert artifacts to React Flow nodes
          const nodes: Node[] = artifacts.map((artifact, index) => {
            // Use saved position or auto-generate one
            const position = nodePositions[artifact.id] || {
              x: 100 + (index % 4) * 250,
              y: 100 + Math.floor(index / 4) * 150,
            };
            return artifactToNode(artifact, position);
          });
          
          // 5. Convert artifact edges to React Flow edges
          const edges: Edge[] = artifactEdges.map(artifactEdgeToFlowEdge);
          
          // 6. Get viewport from canvas_state
          const viewport = project.canvas_state?.viewport || { x: 0, y: 0, zoom: 1 };

          set({
            nodes,
            edges,
            currentProjectId: project.id,
            projectName: project.name,
            viewport,
            history: [],
            historyIndex: -1,
          });
          
          get().takeSnapshot();
        } catch (error: any) {
          console.error("Load project error:", error);
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

      uploadFile: async (file: File) => {
        const { currentProjectId } = get();
        
        if (!currentProjectId) {
          toast.error("Save your project first");
          return;
        }
        
        set({ isUploading: true });
        
        try {
          await api.upload.uploadAndIngest(
            currentProjectId,
            file,
            (job) => {
              // Optional: show progress updates
              console.log(`Job ${job.id} status: ${job.status}`);
            }
          );
          
          toast.success(`${file.name} processed successfully`);
          
          // Refresh artifacts to show new nodes
          await get().refreshArtifacts();
        } catch (error: any) {
          console.error("Upload error:", error);
          toast.error(`Upload failed: ${error.message}`);
        } finally {
          set({ isUploading: false });
        }
      },

      refreshArtifacts: async () => {
        const { currentProjectId } = get();
        
        if (!currentProjectId) return;
        
        try {
          const project = await api.projects.get(currentProjectId);
          const { artifacts, edges: artifactEdges } = await api.projects.getArtifacts(currentProjectId);
          
          const nodePositions = project.canvas_state?.node_positions || {};
          const existingNodes = get().nodes;
          
          // Merge existing positions with saved positions
          const mergedPositions: Record<string, { x: number; y: number }> = { ...nodePositions };
          existingNodes.forEach((node) => {
            mergedPositions[node.id] = { x: node.position.x, y: node.position.y };
          });
          
          // Convert artifacts to nodes
          const nodes: Node[] = artifacts.map((artifact, index) => {
            const position = mergedPositions[artifact.id] || {
              x: 100 + (index % 4) * 250,
              y: 100 + Math.floor(index / 4) * 150,
            };
            return artifactToNode(artifact, position);
          });
          
          const edges: Edge[] = artifactEdges.map(artifactEdgeToFlowEdge);
          
          set({ nodes, edges });
          get().takeSnapshot();
        } catch (error: any) {
          console.error("Refresh error:", error);
          toast.error(`Failed to refresh: ${error.message}`);
        }
      },
    }),
    {
      name: "bee-canvas-storage",
      partialize: (state) => ({
        isHeaderCollapsed: state.isHeaderCollapsed,
        isSidebarCollapsed: state.isSidebarCollapsed,
        showMiniMap: state.showMiniMap,
        viewport: state.viewport,
      }),
    }
  )
);
