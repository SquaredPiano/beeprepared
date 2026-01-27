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
import { getAccessToken } from "@/lib/auth";
import { toast } from "sonner";
import { generateProjectName } from "@/lib/utils/naming";
import { api, Artifact, ArtifactEdge } from "@/lib/api";

// Maps artifact types to node display info
const ARTIFACT_TYPE_CONFIG: Record<string, { label: string; color: string; icon: string }> = {
  video: { label: "Video", color: "#8B5CF6", icon: "Video" },
  audio: { label: "Audio", color: "#EC4899", icon: "Mic" },
  text: { label: "Standard Text", color: "#6B7280", icon: "FileText" },
  flat_text: { label: "Refined Text", color: "#10B981", icon: "FileText" },
  knowledge_core: { label: "Project Core", color: "#F59E0B", icon: "Hexagon" },

  quiz: { label: "Quiz", color: "#3B82F6", icon: "HelpCircle" },
  flashcards: { label: "Flashcards", color: "#8B5CF6", icon: "Layers" },
  notes: { label: "Notes", color: "#10B981", icon: "BookOpen" },
  slides: { label: "Slides", color: "#F97316", icon: "Presentation" },
  exam: { label: "Exam", color: "#EF4444", icon: "ClipboardCheck" },
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
  setNodes: (nodes: Node[] | ((prev: Node[]) => Node[])) => void;
  setEdges: (edges: Edge[] | ((prev: Edge[]) => Edge[])) => void;
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
  autoSave: () => void;
  runFlow: () => Promise<void>;

  loadProject: (id: string) => Promise<void>;
  createNewProject: () => Promise<void>;
  uploadFile: (file: File) => Promise<void>;
  refreshArtifacts: () => Promise<void>;
  clearProject: () => void;
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

      clearProject: () => {
        set({
          currentProjectId: null,
          nodes: [],
          edges: [],
          projectName: generateProjectName()
        });
      },

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

      setNodes: (nodes) => set((state) => ({
        nodes: typeof nodes === 'function' ? (nodes as any)(state.nodes) : nodes
      })),
      setEdges: (edges) => set((state) => ({
        edges: typeof edges === 'function' ? (edges as any)(state.edges) : edges
      })),
      setIsDragging: (isDragging) => set({ isDragging }),
      setIsLocked: (isLocked) => set({ isLocked }),
      setShowMiniMap: (showMiniMap) => set({ showMiniMap }),
      setIsHeaderCollapsed: (isHeaderCollapsed) => set({ isHeaderCollapsed }),
      setIsSidebarCollapsed: (isSidebarCollapsed) => set({ isSidebarCollapsed }),
      setViewport: (viewport) => set({ viewport }),
      setProjectName: (projectName) => {
        set({ projectName });
        get().autoSave();
      },

      onNodesChange: (changes) => {
        if (get().isLocked) return;
        set({
          nodes: applyNodeChanges(changes, get().nodes),
        });
        get().autoSave();
      },

      onEdgesChange: (changes) => {
        if (get().isLocked) return;
        set({
          edges: applyEdgeChanges(changes, get().edges),
        });
        get().autoSave();
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

      autoSave: () => {
        const { currentProjectId, isSaving } = get();
        if (!currentProjectId || isSaving) return;

        // Use a simple timer-based debounce for auto-save
        const timeoutId = (window as any)._autoSaveTimeout;
        if (timeoutId) clearTimeout(timeoutId);

        (window as any)._autoSaveTimeout = setTimeout(() => {
          get().save();
        }, 3000); // Save after 3s of inactivity
      },

      save: async () => {
        const { nodes, edges, currentProjectId, projectName, viewport } = get();
        set({ isSaving: true });

        try {
          const canvas_state = {
            viewport,
            nodes,
            edges,
          };



          if (currentProjectId) {
            const updatedProject = await api.projects.update(currentProjectId, {
              name: projectName,
              canvas_state,
            });
            // Sync back in case server modified it
            set({ projectName: updatedProject.name });
          } else {
            const project = await api.projects.create(projectName, "");
            set({ currentProjectId: project.id });

            const url = new URL(window.location.href);
            url.searchParams.set("id", project.id);
            window.history.pushState({}, "", url.toString());
          }


          // toast.success("Hive saved successfully"); // Disable toast for auto-save to be silent
        } catch (error: any) {
          console.error("Save error:", error);
          // toast.error(`Failed to save: ${error.message}`);
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
          const token = await getAccessToken();
          const response = await fetch(`${process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'}/run`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'Authorization': `Bearer ${token}`
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
          // Clear previous state first
          set({
            nodes: [],
            edges: [],
            currentProjectId: id,
            history: [],
            historyIndex: -1
          });

          // 1. Load project metadata
          const project = await api.projects.get(id);
          set({ projectName: project.name });

          // 2. Load artifacts AND edges
          const { artifacts, edges: artifactEdges } = await api.projects.getArtifacts(id);

          let nodes: Node[] = [];

          // If we have saved canvas state, use it as base (positions)
          // But we MUST sync the data with real artifacts
          if (project.canvas_state?.nodes && project.canvas_state.nodes.length > 0) {
            const generatorTypes = ['quiz', 'notes', 'slides', 'flashcards', 'exam'];

            nodes = project.canvas_state.nodes
              .filter(node => {
                // FILTER OUT duplicate artifactNodes for generator types
                // We only want 'generator' nodes for these, not 'artifactNode' pills
                if (node.type === 'artifactNode' && generatorTypes.includes(node.data?.type)) {
                  return false;
                }
                return true;
              })
              .map(node => {
                // Update data if it corresponds to an artifact
                if (node.type === 'asset' || node.type === 'artifactNode' || node.type === 'result' || node.type === 'generator') {
                  const artifactId = node.id; // Assuming node ID is artifact ID for synced nodes
                  const artifact = artifacts.find(a => a.id === artifactId || (node.data?.artifact as any)?.id === artifactId);
                  if (artifact) {
                    return {
                      ...node,
                      data: {
                        ...node.data,
                        artifact,
                        status: 'completed'
                      }
                    };
                  }
                }
                return node;
              });
          } else {
            // 3. Fresh Layout Generation
            // Source (Asset)
            const sourceArtifact = artifacts.find(a => ['video', 'audio', 'pdf', 'text', 'flat_text'].includes(a.type));
            if (sourceArtifact) {
              nodes.push({
                id: sourceArtifact.id,
                type: 'asset',
                position: { x: 100, y: 300 },
                data: {
                  label: sourceArtifact.content?.filename || sourceArtifact.type,
                  type: sourceArtifact.type,
                  status: 'completed',
                  artifact: sourceArtifact
                }
              });
            }

            // Generators
            // Only spawn if we actually have artifacts (don't clutter canvas with idle nodes)
            const existingGenerators = artifacts.filter(a => ['quiz', 'notes', 'slides', 'flashcards', 'exam'].includes(a.type));

            existingGenerators.forEach((gen, idx) => {
              nodes.push({
                id: gen.id,
                type: 'generator',
                position: { x: 500, y: 50 + (idx * 150) },
                data: {
                  label: (ARTIFACT_TYPE_CONFIG[gen.type] || {}).label || gen.type,
                  subType: gen.type,
                  projectId: id,
                  status: 'completed',
                  artifact: gen,
                  progress: 100
                }
              });
            });
          }

          // Generate Edges (Restore or Auto-connect)
          let edges: Edge[] = [];

          if (project.canvas_state?.edges && project.canvas_state.edges.length > 0) {
            edges = project.canvas_state.edges;
          } else {
            // Auto-connect Source -> Generators (Default for fresh projects)
            const sourceNode = nodes.find(n => n.type === 'asset');
            if (sourceNode) {
              nodes.filter(n => n.type === 'generator').forEach(gen => {
                edges.push({
                  id: `e-${sourceNode.id}-${gen.id}`,
                  source: sourceNode.id,
                  target: gen.id,
                  animated: true,
                  markerEnd: { type: MarkerType.ArrowClosed, color: "#F59E0B" },
                  style: { stroke: '#F59E0B', strokeWidth: 2, strokeDasharray: '5 5' }
                });
              });
            }
          }

          set({ nodes, edges });
          get().takeSnapshot();

        } catch (error: any) {
          console.error("Load project error:", error);
          toast.error("Failed to load project");
        }
      },

      refreshArtifacts: async () => {
        const { currentProjectId, nodes } = get();
        if (!currentProjectId) return;

        try {
          const { artifacts } = await api.projects.getArtifacts(currentProjectId);
          console.log('[refreshArtifacts] Got', artifacts.length, 'artifacts:', artifacts.map(a => a.type));

          // ONLY update existing nodes - do NOT create new nodes
          // Nodes are created by: 1) drag-drop from sidebar, 2) loadProject
          const updatedNodes = nodes.map(node => {
            // Update generator nodes with their corresponding artifact
            if (node.type === 'generator' && node.data.subType) {
              const relevantArtifact = artifacts.find(a => a.type === node.data.subType);
              if (relevantArtifact) {
                console.log('[refreshArtifacts] Updating generator', node.data.subType, 'with artifact');
                return {
                  ...node,
                  data: { ...node.data, status: 'completed', artifact: relevantArtifact, progress: 100 }
                };
              }
            }

            // Update asset nodes with their artifact data
            if (node.type === 'asset' && (node.data as any).artifact?.id) {
              const refreshed = artifacts.find(a => a.id === (node.data as any).artifact.id);
              if (refreshed) {
                return { ...node, data: { ...node.data, artifact: refreshed } };
              }
            }

            // Update artifactNode (knowledge_core etc) if it exists
            if (node.type === 'artifactNode' && (node.data as any).artifact?.id) {
              const refreshed = artifacts.find(a => a.id === (node.data as any).artifact.id);
              if (refreshed) {
                return { ...node, data: { ...node.data, artifact: refreshed, status: 'completed' } };
              }
            }

            return node;
          });

          set({ nodes: updatedNodes });
          console.log('[refreshArtifacts] Updated', updatedNodes.length, 'nodes');

        } catch (error) {
          console.error("Refresh error", error);
        }
      },

      createNewProject: async () => {
        const projectName = generateProjectName();
        try {
          const project = await api.projects.create(projectName, "");
          set({
            currentProjectId: project.id,
            projectName: project.name,
            nodes: [],
            edges: [],
            history: [],
            historyIndex: -1
          });

          // Update URL
          const url = new URL(window.location.href);
          url.searchParams.set("id", project.id);
          window.history.pushState({}, "", url.toString());

          toast.success("New project created!");
        } catch (error: any) {
          console.error("Create project error:", error);
          toast.error(`Failed to create project: ${error.message}`);
        }
      },

      uploadFile: async (file: File) => {
        const { currentProjectId } = get();
        if (!currentProjectId) {
          toast.error("Create a project first");
          return;
        }

        set({ isUploading: true });
        try {
          await api.upload.uploadAndIngest(currentProjectId, file, "/", (job) => {
            console.log("Upload job status:", job.status);
          });

          toast.success(`Uploaded ${file.name}`);

          // Reload project to get new artifacts
          await get().loadProject(currentProjectId);
        } catch (error: any) {
          console.error("Upload error:", error);
          toast.error(`Upload failed: ${error.message}`);
        } finally {
          set({ isUploading: false });
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
