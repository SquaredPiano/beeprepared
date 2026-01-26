"use client";

import { useCallback, useState, useMemo, useRef, useEffect } from "react";
import {
  ReactFlow,
  Background,
  MiniMap,
  addEdge,
  type OnConnect,
  MarkerType,
  ConnectionMode,
  BackgroundVariant,
  Panel,
  useReactFlow,
  ReactFlowProvider,
  Node,
  Edge,
  Connection,
  Viewport,
} from "@xyflow/react";

import "@xyflow/react/dist/style.css";
import useSound from "use-sound";
import { toast } from "sonner";
import { useSearchParams } from "next/navigation";
import { AlertCircle } from "lucide-react";

import { useCanvasStore } from "@/store/useCanvasStore";
import { AssetNode } from "./nodes/AssetNode";
import { ProcessNode } from "./nodes/ProcessNode";
import { ResultNode } from "./nodes/ResultNode";
import { ArtifactNode } from "./nodes/ArtifactNode";
import { GeneratorNode } from "./nodes/GeneratorNode";

import { CanvasHeader } from "./CanvasHeader";
import { CanvasSidebar } from "./CanvasSidebar";
import { CanvasControls } from "./CanvasControls";
import { AssetUploadModal } from "./AssetUploadModal";
import { DeleteConfirmationDialog } from "./DeleteConfirmationDialog";
import { NodeContextMenu } from "./NodeContextMenu";

// Modals
import { AssetPreviewModal } from "./modals/AssetPreviewModal";
import { ProcessStatusModal } from "./modals/ProcessStatusModal";
import { ArtifactPreviewModal } from "./modals/ArtifactPreviewModal";

const nodeTypes = {
  asset: AssetNode,
  process: ProcessNode,
  result: ResultNode,
  artifactNode: ArtifactNode,
  generator: GeneratorNode,
};

function BeeCanvasInner() {
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    setNodes,
    setEdges,
    loadProject,
    refreshArtifacts, // Ensure this is destructured
    currentProjectId,
    takeSnapshot,
    isDragging,
    setIsDragging,
    isLocked,
    showMiniMap,
    viewport,
    setViewport,
    projectName
  } = useCanvasStore();

  const { screenToFlowPosition, fitView } = useReactFlow();

  const searchParams = useSearchParams();
  const projectId = searchParams.get("id");

  // Local UI State
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [nodesToDelete, setNodesToDelete] = useState<Node[]>([]);

  // Preview Modals State
  const [previewAsset, setPreviewAsset] = useState<any>(null);
  const [previewProcess, setPreviewProcess] = useState<any>(null);
  const [previewArtifact, setPreviewArtifact] = useState<any>(null);
  const [contextMenu, setContextMenu] = useState<{ id: string; top: number; left: number } | null>(null);

  // Sounds

  const [playConnect] = useSound("/sounds/connect.mp3", { volume: 0.5 });
  const [playClick] = useSound("/sounds/click.mp3", { volume: 0.3 });
  const [playComplete] = useSound("/sounds/complete.mp3", { volume: 0.6 });
  const [playDelete] = useSound("/sounds/delete.mp3", { volume: 0.4 });

  // Initial Load
  useEffect(() => {
    if (projectId && projectId !== currentProjectId) {
      loadProject(projectId);
    }
  }, [projectId, loadProject, currentProjectId]);

  // Polling for Updates
  useEffect(() => {
    if (!currentProjectId) return;

    const interval = setInterval(() => {
      refreshArtifacts();
    }, 5000); // Poll every 5 seconds

    return () => clearInterval(interval);
  }, [currentProjectId, refreshArtifacts]);

  // Constraints & Auto-connect logic
  const findNearestCompatibleNode = (
    position: { x: number, y: number },
    targetType: 'asset' | 'process' | 'knowledge_core'
  ): Node | null => {
    const threshold = 300;
    let nearest: Node | null = null;
    let minDistance = threshold;

    for (const node of nodes) {
      // For knowledge_core, look for artifactNode with type knowledge_core
      if (targetType === 'knowledge_core') {
        if (node.type !== 'artifactNode' || node.data?.type !== 'knowledge_core') continue;
      } else {
        if (node.type !== targetType) continue;
      }

      const distance = Math.sqrt(
        Math.pow(node.position.x - position.x, 2) +
        Math.pow(node.position.y - position.y, 2)
      );

      if (distance < minDistance) {
        minDistance = distance;
        nearest = node;
      }
    }

    return nearest;
  };

  const autoConnectNode = useCallback((newNode: Node) => {
    if (newNode.type === 'process') {
      const sourceNode = findNearestCompatibleNode(newNode.position, 'asset');
      if (sourceNode) {
        const edge: Edge = {
          id: `e${sourceNode.id}-${newNode.id}`,
          source: sourceNode.id,
          target: newNode.id,
          animated: true,
          markerEnd: { type: MarkerType.ArrowClosed, color: "#3B82F6" },
          style: { stroke: "#3B82F6", strokeWidth: 2, strokeDasharray: "5 5" }
        };
        setEdges([...edges, edge]);
        playConnect();
        toast.success(`Connected to ${sourceNode.data.label || 'Asset'}`);
      }
    } else if (newNode.type === 'result') {
      const sourceNode = findNearestCompatibleNode(newNode.position, 'process');
      if (sourceNode) {
        const edge: Edge = {
          id: `e${sourceNode.id}-${newNode.id}`,
          source: sourceNode.id,
          target: newNode.id,
          animated: true,
          markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" },
          style: { stroke: "#FCD34F", strokeWidth: 2, strokeDasharray: "5 5" }
        };
        setEdges([...edges, edge]);
        playConnect();
        toast.success(`Output connected to processor`);
      }
    } else if (newNode.type === 'generator') {
      // Smart auto-connect: Find nearest asset OR generator for chaining
      const nearestAsset = findNearestCompatibleNode(newNode.position, 'asset');

      // Also find nearest generator (for chaining Quiz -> Flashcards)
      let nearestGenerator: Node | null = null;
      let genDistance = 300; // threshold
      for (const node of nodes) {
        if (node.type === 'generator' && node.id !== newNode.id) {
          const distance = Math.sqrt(
            Math.pow(node.position.x - newNode.position.x, 2) +
            Math.pow(node.position.y - newNode.position.y, 2)
          );
          if (distance < genDistance) {
            genDistance = distance;
            nearestGenerator = node;
          }
        }
      }

      // Calculate asset distance
      let assetDistance = 9999;
      if (nearestAsset) {
        assetDistance = Math.sqrt(
          Math.pow(nearestAsset.position.x - newNode.position.x, 2) +
          Math.pow(nearestAsset.position.y - newNode.position.y, 2)
        );
      }

      // Connect to whichever is closer
      const sourceNode = (nearestGenerator && genDistance < assetDistance) ? nearestGenerator : nearestAsset;

      if (sourceNode) {
        const isChained = sourceNode.type === 'generator';
        const edge: Edge = {
          id: `e${sourceNode.id}-${newNode.id}`,
          source: sourceNode.id,
          target: newNode.id,
          animated: true,
          markerEnd: { type: MarkerType.ArrowClosed, color: isChained ? "#8B5CF6" : "#F59E0B" },
          style: { stroke: isChained ? "#8B5CF6" : "#F59E0B", strokeWidth: 2, strokeDasharray: "5 5" }
        };
        setEdges([...edges, edge]);
        playConnect();
        toast.success(isChained
          ? `Chained to ${(sourceNode.data as any).label || 'Generator'}`
          : `Connected to Source`
        );
      }
    }
  }, [nodes, edges, setEdges, playConnect]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback((event: React.DragEvent) => {
    event.preventDefault();

    const dataStr = event.dataTransfer.getData("application/reactflow");
    if (!dataStr) return;

    const nodeData = JSON.parse(dataStr);

    // Check constraints
    const hasSource = nodes.some(n => n.type === 'asset');
    const hasProcess = nodes.some(n => n.type === 'process');
    const hasKnowledgeCore = nodes.some(n =>
      n.type === 'artifactNode' && n.data?.type === 'knowledge_core'
    );

    if (nodeData.type === 'process' && !hasSource) {
      toast.warning("Add a Source First", {
        description: "Upload a file before adding processors.",
        icon: <AlertCircle className="h-4 w-4" />,
      });
      return;
    }

    if (nodeData.type === 'result' && !hasProcess) {
      toast.warning("Add a Processor First", {
        description: "Add a processor to handle your files before creating outputs.",
        icon: <AlertCircle className="h-4 w-4" />,
      });
      return;
    }

    // Generator nodes need a knowledge core (but we'll be lenient and allow adding them)
    // They'll show an error message when trying to generate without one
    // Generator nodes need a source
    if (nodeData.type === 'generator' && !hasSource) {
      toast.info("No Source Yet", {
        description: "Upload a source file to enable generation.",
        icon: <AlertCircle className="h-4 w-4" />,
      });
      // Still allow adding the node
    }


    const position = screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });

    const newNode: Node = {
      id: `${nodeData.type}-${Date.now()}`,
      type: nodeData.type,
      position,
      data: {
        ...nodeData,
        status: nodeData.type === 'process' ? 'pending' : nodeData.type === 'generator' ? 'idle' : 'ready',
        progress: 0,
        stage: 'extraction'
      },
    };

    setNodes([...nodes, newNode]);
    autoConnectNode(newNode);
    takeSnapshot();
    playClick();
  }, [nodes, setNodes, screenToFlowPosition, autoConnectNode, takeSnapshot, playClick]);

  // Handle deletion with confirmation
  const onNodesDelete = useCallback((deletedNodes: Node[]) => {
    const hasImportant = deletedNodes.some(n =>
      n.type === 'asset' ||
      (n.type === 'process' && n.data.status === 'complete') ||
      n.type === 'result'
    );

    if (hasImportant) {
      setNodesToDelete(deletedNodes);
      setDeleteDialogOpen(true);
      return false; // Prevent immediate deletion
    }

    takeSnapshot();
    playDelete();
    return true;
  }, [takeSnapshot, playDelete]);

  const confirmDelete = () => {
    const deletedIds = new Set(nodesToDelete.map(n => n.id));
    setNodes(nodes.filter(n => !deletedIds.has(n.id)));
    setEdges(edges.filter(e => !deletedIds.has(e.source) && !deletedIds.has(e.target)));
    setDeleteDialogOpen(false);
    setNodesToDelete([]);
    takeSnapshot();
    playDelete();
  };

  // Node interaction handlers
  const onNodeClick = useCallback((_: any, node: Node) => {
    if (node.type === 'asset') setPreviewAsset(node.data);
    else if (node.type === 'process') setPreviewProcess(node.data);
    else if (node.type === 'result') setPreviewArtifact({ ...node.data, id: node.id });
    else if (node.type === 'artifactNode' && node.data?.artifact) {
      // Show artifact preview for artifact nodes
      setPreviewArtifact(node.data.artifact);
    }
    // Generator nodes handle their own click via internal button
  }, []);

  const onViewportChange = useCallback((viewport: Viewport) => {
    useCanvasStore.getState().setViewport(viewport);
  }, []);

  // Edge styling logic
  const styledEdges = useMemo(() => {

    return edges.map(edge => {
      const sourceNode = nodes.find(n => n.id === edge.source);
      const color = sourceNode?.type === 'asset' ? "#3B82F6" : "#FCD34F";

      return {
        ...edge,
        animated: !isDragging,
        style: {
          stroke: color,
          strokeWidth: isDragging ? 3 : 2,
          strokeDasharray: isDragging ? "none" : "5 5",
          transition: 'stroke-width 0.2s, stroke-dasharray 0.2s',
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color,
        }
      };
    });
  }, [edges, nodes, isDragging]);

  return (
    <div className="w-full h-full relative bg-[#FBFBFB] overflow-hidden" onDrop={onDrop} onDragOver={onDragOver}>
      <CanvasHeader />
      <CanvasSidebar onIngestClick={() => setIsUploadModalOpen(true)} />
      <CanvasControls />

      <ReactFlow
        nodes={nodes}
        edges={styledEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeDragStart={() => setIsDragging(true)}
        onNodeDragStop={() => setIsDragging(false)}
        onNodeClick={onNodeClick}
        onNodesDelete={onNodesDelete}
        onViewportChange={onViewportChange}
        defaultViewport={viewport}
        nodeTypes={nodeTypes}
        connectionMode={ConnectionMode.Loose}
        nodesDraggable={!isLocked}
        nodesConnectable={!isLocked}
        elementsSelectable={!isLocked}
        panOnDrag={!isLocked}
        zoomOnScroll={!isLocked}
        fitView
        className="bg-transparent"
      >
        <Background
          color="#FCD34F"
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1}
          className="opacity-[0.15]"
        />
        {showMiniMap && (
          <MiniMap
            nodeColor={(n) => n.type === 'asset' ? '#3B82F6' : n.type === 'result' ? '#FCD34F' : '#0F172A'}
            className="!rounded-2xl !border-wax"
          />
        )}
      </ReactFlow>


      {/* Delete Confirmation */}
      <DeleteConfirmationDialog
        open={deleteDialogOpen}
        onOpenChange={setDeleteDialogOpen}
        onConfirm={confirmDelete}
        title="Delete Node?"
        description="This will remove the node and all its connections."
        itemName={nodesToDelete.map(n => n.data.label).join(', ')}
      />

      {/* Preview Modals */}
      <AssetPreviewModal
        isOpen={!!previewAsset}
        onClose={() => setPreviewAsset(null)}
        asset={previewAsset}
      />
      <ProcessStatusModal
        isOpen={!!previewProcess}
        onClose={() => setPreviewProcess(null)}
        process={previewProcess}
      />
      <ArtifactPreviewModal
        isOpen={!!previewArtifact}
        onClose={() => setPreviewArtifact(null)}
        artifact={previewArtifact}
      />

      {/* Upload Modal Relay */}
      <AssetUploadModal
        isOpen={isUploadModalOpen}
        onClose={() => setIsUploadModalOpen(false)}
        onUpload={(asset) => {
          const newNode: Node = {
            id: `asset-${Date.now()}`,
            type: "asset",
            position: { x: 100, y: 300 },
            data: asset,
          };
          setNodes([...nodes, newNode]);
          takeSnapshot();
          playComplete();
        }}
      />
    </div>
  );
}

export function BeeCanvas() {
  return (
    <ReactFlowProvider>
      <BeeCanvasInner />
    </ReactFlowProvider>
  );
}
