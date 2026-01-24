"use client";

import React, { useCallback, useMemo } from "react";
import { 
  ReactFlow, 
  Background, 
  Controls, 
  BackgroundVariant, 
  NodeTypes, 
  ConnectionMode,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Edge,
  Node,
  MarkerType,
  useReactFlow,
  ReactFlowProvider
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AgentNode } from "./AgentNode";
import { useIngestionStore } from "@/store/ingestionStore";
import { playSound } from "@/lib/sounds";

const nodeTypes: NodeTypes = {
  agent: AgentNode,
};

const initialEdges: Edge[] = [
  { id: "e1-2", source: "ingest", target: "extract", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
  { id: "e2-3", source: "extract", target: "categorize", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
  { id: "e3-4", source: "categorize", target: "generate", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
  { id: "e4-5", source: "generate", target: "finalize", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
];

function PipelineCanvasContent() {
  const { tasks } = useIngestionStore();
  const { screenToFlowPosition } = useReactFlow();

  const initialNodes: Node[] = useMemo(() => [
    { id: "ingest", type: "agent", position: { x: 50, y: 350 }, data: { label: "Ingestion Agent", type: "ingest", role: "Input Gateway", status: "completed" } },
    { id: "extract", type: "agent", position: { x: 450, y: 350 }, data: { label: "Extraction Agent", type: "extract", role: "Structural Analyst", status: "processing" } },
    { id: "categorize", type: "agent", position: { x: 850, y: 350 }, data: { label: "Cognitive Agent", type: "categorize", role: "Matrix Manager", status: "idle" } },
    { id: "generate", type: "agent", position: { x: 1250, y: 350 }, data: { label: "Synthesis Agent", type: "generate", role: "Content Creator", status: "idle" } },
    { id: "finalize", type: "agent", position: { x: 1650, y: 350 }, data: { label: "Archival Agent", type: "finalize", role: "Library Manager", status: "idle" } },
  ], []);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    (params: Connection) => {
      playSound("connect");
      setEdges((eds) => addEdge({
        ...params,
        animated: true,
        markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" },
        style: { stroke: "#FCD34F", strokeWidth: 2 }
      }, eds));
    },
    [setEdges]
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const dataStr = event.dataTransfer.getData("application/reactflow");
      if (!dataStr) return;

      const agent = JSON.parse(dataStr);
      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newNode: Node = {
        id: `${agent.type}-${Date.now()}`,
        type: "agent",
        position,
        data: { 
          ...agent,
          status: "idle"
        },
      };

      playSound("drop");
      setNodes((nds) => nds.concat(newNode));
    },
    [screenToFlowPosition, setNodes]
  );

  return (
    <div className="w-full h-full glass rounded-[3rem] border border-border/40 overflow-hidden relative group">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        nodeTypes={nodeTypes}
        connectionMode={ConnectionMode.Loose}
        fitView
        className="bg-stone-50/20"
      >
        <Background 
          variant={BackgroundVariant.Lines} 
          gap={48} 
          size={1} 
          color="rgba(252, 211, 79, 0.05)" 
        />
        <Controls 
          className="!bg-white !border-border/40 !rounded-2xl !shadow-xl !m-6 [&>button]:!bg-white [&>button]:!border-0 [&>button]:!border-b [&>button]:!border-border/10 [&>button:last-child]:!border-0 [&>button]:!w-10 [&>button]:!h-10 [&>button]:hover:!bg-honey-50 [&>button]:!text-bee-black [&>button]:!transition-colors [&>button]:cursor-pointer" 
        />
      </ReactFlow>
      
      {/* Overlay Status */}
      <div className="absolute top-8 left-8 z-10 pointer-events-none">
        <div className="glass px-6 py-3 rounded-2xl border border-border/40 space-y-1">
          <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-honey-600">Cognitive Pipeline</p>
          <p className="text-sm font-display font-bold tracking-tight uppercase">Agent Autonomy Visualization</p>
        </div>
      </div>

      <div className="absolute bottom-8 right-8 z-10">
        <div className="glass px-6 py-3 rounded-2xl border border-border/40 flex items-center gap-4">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-honey-500 animate-pulse" />
            <span className="text-[8px] uppercase tracking-widest font-bold opacity-60">Live Feed</span>
          </div>
          <div className="w-px h-4 bg-border/40" />
          <span className="text-[8px] uppercase tracking-widest font-bold opacity-40">{nodes.length} Agents Scaled</span>
        </div>
      </div>
    </div>
  );
}

export function PipelineCanvas() {
  return (
    <ReactFlowProvider>
      <PipelineCanvasContent />
    </ReactFlowProvider>
  );
}
