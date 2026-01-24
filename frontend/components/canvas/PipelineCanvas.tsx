"use client";

import React, { useCallback, useMemo, useState } from "react";
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
  ReactFlowProvider,
  Panel
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AgentNode } from "./AgentNode";
import { useIngestionStore } from "@/store/ingestionStore";
import { useFlowStore } from "@/store/useFlowStore";
import { playSound } from "@/lib/sounds";
import { Undo2, Redo2, Save, Maximize, RotateCcw, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";

const nodeTypes: NodeTypes = {
  agent: AgentNode,
};

function PipelineCanvasContent() {
  const { tasks } = useIngestionStore();
  const { screenToFlowPosition, fitView, zoomTo } = useReactFlow();
  const { 
    nodes, 
    edges, 
    onNodesChange, 
    onEdgesChange, 
    onConnect, 
    undo, 
    redo, 
    save, 
    takeSnapshot,
    setNodes,
    setEdges 
  } = useFlowStore();

  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);

  // Initialize nodes if empty
  React.useEffect(() => {
    if (nodes.length === 0) {
      const initialNodes: Node[] = [
        { id: "ingest", type: "agent", position: { x: 50, y: 350 }, data: { label: "Ingestion Agent", type: "ingest", role: "Input Gateway", status: "completed" } },
        { id: "extract", type: "agent", position: { x: 450, y: 350 }, data: { label: "Extraction Agent", type: "extract", role: "Structural Analyst", status: "processing" } },
        { id: "categorize", type: "agent", position: { x: 850, y: 350 }, data: { label: "Cognitive Agent", type: "categorize", role: "Matrix Manager", status: "idle" } },
        { id: "generate", type: "agent", position: { x: 1250, y: 350 }, data: { label: "Synthesis Agent", type: "generate", role: "Content Creator", status: "idle" } },
        { id: "finalize", type: "agent", position: { x: 1650, y: 350 }, data: { label: "Archival Agent", type: "finalize", role: "Library Manager", status: "idle" } },
      ];
      const initialEdges: Edge[] = [
        { id: "e1-2", source: "ingest", target: "extract", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
        { id: "e2-3", source: "extract", target: "categorize", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
        { id: "e3-4", source: "categorize", target: "generate", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
        { id: "e4-5", source: "generate", target: "finalize", animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#FCD34F" }, style: { stroke: "#FCD34F", strokeWidth: 2 } },
      ];
      setNodes(initialNodes);
      setEdges(initialEdges);
      takeSnapshot();
    }
  }, []);

  const onContextMenu = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      setMenu({ x: event.clientX, y: event.clientY });
    },
    [setMenu]
  );

  const onPaneClick = useCallback(() => setMenu(null), [setMenu]);

  const handleResetView = () => {
    fitView({ padding: 0.2, duration: 800 });
    playSound("drop");
    setMenu(null);
  };

  const handleUndo = () => {
    undo();
    playSound("pickup");
    setMenu(null);
  };

  const handleRedo = () => {
    redo();
    playSound("pickup");
    setMenu(null);
  };

  const handleSave = () => {
    save();
    playSound("complete");
    setMenu(null);
  };

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
        data: { ...agent, status: "idle" },
      };

      playSound("drop");
      setNodes([...nodes, newNode]);
      takeSnapshot();
    },
    [screenToFlowPosition, nodes, setNodes, takeSnapshot]
  );

  return (
    <div 
      className="w-full h-full glass rounded-[3rem] border border-border/40 relative group"
      onContextMenu={onContextMenu}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onDrop={onDrop}
        onDragOver={onDragOver}
        onPaneClick={onPaneClick}
        nodeTypes={nodeTypes}
        connectionMode={ConnectionMode.Loose}
        fitView
        className="bg-stone-50/20 rounded-[3rem]"
      >
        <Background 
          variant={BackgroundVariant.Lines} 
          gap={48} 
          size={1} 
          color="rgba(252, 211, 79, 0.05)" 
        />
        
        <Panel position="top-right" className="flex items-center gap-2 m-6">
          <div className="glass flex items-center p-1.5 rounded-2xl border border-border/40 shadow-xl">
            <button 
              onClick={handleUndo}
              className="p-3 hover:bg-honey-50 rounded-xl transition-colors cursor-pointer group"
              title="Undo (Ctrl+Z)"
            >
              <Undo2 size={18} className="opacity-40 group-hover:opacity-100 group-hover:text-honey-600" />
            </button>
            <button 
              onClick={handleRedo}
              className="p-3 hover:bg-honey-50 rounded-xl transition-colors cursor-pointer group"
              title="Redo (Ctrl+Y)"
            >
              <Redo2 size={18} className="opacity-40 group-hover:opacity-100 group-hover:text-honey-600" />
            </button>
            <div className="w-px h-6 bg-border/20 mx-1" />
            <button 
              onClick={handleSave}
              className="p-3 hover:bg-honey-50 rounded-xl transition-colors cursor-pointer group"
              title="Export JSON"
            >
              <Save size={18} className="opacity-40 group-hover:opacity-100 group-hover:text-honey-600" />
            </button>
            <button 
              onClick={handleResetView}
              className="p-3 hover:bg-honey-50 rounded-xl transition-colors cursor-pointer group"
              title="Reset View"
            >
              <RotateCcw size={18} className="opacity-40 group-hover:opacity-100 group-hover:text-honey-600" />
            </button>
          </div>
        </Panel>

        <Controls 
          showInteractive={false}
          className="!bg-white !border-border/40 !rounded-2xl !shadow-xl !m-6 [&>button]:!bg-white [&>button]:!border-0 [&>button]:!border-b [&>button]:!border-border/10 [&>button:last-child]:!border-0 [&>button]:!w-10 [&>button]:!h-10 [&>button]:hover:!bg-honey-50 [&>button]:!text-bee-black [&>button]:!transition-colors [&>button]:cursor-pointer" 
        />
      </ReactFlow>
      
      {/* Context Menu */}
      {menu && (
        <div 
          style={{ top: menu.y - 100, left: menu.x - 300 }}
          className="fixed z-[100] w-56 glass border border-border/40 rounded-2xl shadow-2xl p-2 animate-in fade-in zoom-in duration-200"
        >
          <button 
            onClick={handleUndo}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-honey-50 rounded-xl transition-colors text-xs font-bold uppercase tracking-widest cursor-pointer group"
          >
            <div className="flex items-center gap-3">
              <Undo2 size={14} className="opacity-40 group-hover:opacity-100" />
              Undo
            </div>
            <span className="opacity-20 text-[10px]">Ctrl+Z</span>
          </button>
          <button 
            onClick={handleRedo}
            className="w-full flex items-center justify-between px-4 py-3 hover:bg-honey-50 rounded-xl transition-colors text-xs font-bold uppercase tracking-widest cursor-pointer group"
          >
            <div className="flex items-center gap-3">
              <Redo2 size={14} className="opacity-40 group-hover:opacity-100" />
              Redo
            </div>
            <span className="opacity-20 text-[10px]">Ctrl+Y</span>
          </button>
          <div className="h-px bg-border/40 my-2" />
          <button 
            onClick={handleSave}
            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-honey-50 rounded-xl transition-colors text-xs font-bold uppercase tracking-widest cursor-pointer group"
          >
            <Save size={14} className="opacity-40 group-hover:opacity-100" />
            Save Pipeline
          </button>
          <button 
            onClick={handleResetView}
            className="w-full flex items-center gap-3 px-4 py-3 hover:bg-honey-50 rounded-xl transition-colors text-xs font-bold uppercase tracking-widest cursor-pointer group"
          >
            <RotateCcw size={14} className="opacity-40 group-hover:opacity-100" />
            Default View
          </button>
        </div>
      )}

      {/* Overlay Status */}
      <div className="absolute top-8 left-8 z-10 pointer-events-none">
        <div className="glass px-6 py-3 rounded-2xl border border-border/40 space-y-1">
          <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-honey-600">Cognitive Pipeline</p>
          <p className="text-sm font-display font-bold tracking-tight uppercase">Agent Autonomy Visualization</p>
        </div>
      </div>

      <div className="absolute bottom-8 right-8 z-10 pointer-events-none">
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
