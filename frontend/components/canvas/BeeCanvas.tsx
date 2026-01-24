"use client";

import { useCallback, useState, useMemo, useRef, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type OnConnect,
  MarkerType,
  ConnectionMode,
  BackgroundVariant,
  Panel,
  useReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import useSound from "use-sound";

import { AssetNode } from "./nodes/AssetNode";
import { ProcessNode } from "./nodes/ProcessNode";
import { ResultNode } from "./nodes/ResultNode";
import { AssetUploadModal } from "./AssetUploadModal";
import { Button } from "@/components/ui/button";
import { 
  Plus, 
  Upload, 
  Play, 
  Save, 
  Undo2, 
  Redo2, 
  Maximize2, 
  Trash2, 
  MousePointer2,
  Box,
  Zap,
  Layers,
  Sparkles
} from "lucide-react";
import { toast } from "sonner";
import { useFlowStore } from "@/store/useFlowStore";
import { useSearchParams } from "next/navigation";
import { 
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from "@/components/ui/context-menu";

const nodeTypes = {
  asset: AssetNode,
  process: ProcessNode,
  result: ResultNode,
};

function BeeCanvasInner() {
  const { 
    nodes, 
    edges, 
    onNodesChange, 
    onEdgesChange, 
    onConnect, 
    undo, 
    redo, 
    save, 
    loadProject, 
    currentProjectId,
    takeSnapshot
  } = useFlowStore();
  
  const { screenToFlowPosition, fitView, zoomIn, zoomOut } = useReactFlow();
  const searchParams = useSearchParams();
  const projectId = searchParams.get("id");
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [menuPosition, setMenuPosition] = useState({ x: 0, y: 0 });

  // Sounds
  const [playConnect] = useSound("/sounds/connect.mp3", { volume: 0.5 });
  const [playClick] = useSound("/sounds/click.mp3", { volume: 0.3 });
  const [playComplete] = useSound("/sounds/complete.mp3", { volume: 0.6 });
  const [playDelete] = useSound("/sounds/delete.mp3", { volume: 0.4 });

  useEffect(() => {
    if (projectId && projectId !== currentProjectId) {
      loadProject(projectId);
    }
  }, [projectId, loadProject, currentProjectId]);

  const onConnectWrapped: OnConnect = useCallback(
    (params) => {
      onConnect(params);
      playConnect();
    },
    [onConnect, playConnect]
  );

  const handleAssetUpload = (asset: { label: string; type: 'pdf' | 'video' | 'pptx' }) => {
    const id = `asset-${Date.now()}`;
    const newNode = {
      id,
      type: "asset",
      position: { x: 100, y: 300 },
      data: { ...asset },
    };
    useFlowStore.getState().setNodes([...nodes, newNode]);
    takeSnapshot();
    playComplete();
  };

  const addNodeAtPosition = (type: string, data: any, position?: { x: number, y: number }) => {
    const id = `${type}-${Date.now()}`;
    const pos = position || { x: Math.random() * 400, y: Math.random() * 400 };
    const newNode = {
      id,
      type,
      position: pos,
      data,
    };
    useFlowStore.getState().setNodes([...nodes, newNode]);
    takeSnapshot();
    playClick();
  };

  const handleContextMenu = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    setMenuPosition({ x: event.clientX, y: event.clientY });
  }, []);

  return (
    <div className="w-full h-full relative bg-cream/5" onContextMenu={handleContextMenu}>
      <ContextMenu>
        <ContextMenuTrigger className="w-full h-full block">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnectWrapped}
            nodeTypes={nodeTypes}
            connectionMode={ConnectionMode.Loose}
            fitView
            className="bg-transparent"
            defaultEdgeOptions={{
              type: 'bezier',
              animated: true,
              style: { strokeWidth: 3, stroke: '#FCD34F' },
              markerEnd: { type: MarkerType.ArrowClosed, color: '#FCD34F' }
            }}
          >
            <Background color="#FCD34F" variant={BackgroundVariant.Dots} gap={24} size={1.5} className="opacity-30" />
            
            <Panel position="top-center" className="mt-4">
              <div className="flex items-center gap-3 p-2 bg-white/90 backdrop-blur-xl rounded-[1.5rem] border border-wax shadow-2xl shadow-honey/10 z-50 ring-1 ring-black/[0.03]">
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-10 px-4 gap-2 rounded-xl hover:bg-honey/10 text-bee-black font-bold uppercase text-[10px] tracking-widest cursor-pointer"
                  onClick={() => setIsUploadModalOpen(true)}
                >
                  <Upload className="w-3.5 h-3.5" /> Ingest
                </Button>
                <div className="w-px h-4 bg-wax" />
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-10 px-4 gap-2 rounded-xl hover:bg-honey/10 text-bee-black font-bold uppercase text-[10px] tracking-widest cursor-pointer"
                  onClick={() => addNodeAtPosition('process', { label: 'Synthesize', status: 'pending' })}
                >
                  <Plus className="w-3.5 h-3.5" /> Process
                </Button>
                <Button 
                  variant="ghost" 
                  size="sm" 
                  className="h-10 px-4 gap-2 rounded-xl hover:bg-honey/10 text-bee-black font-bold uppercase text-[10px] tracking-widest cursor-pointer"
                  onClick={() => addNodeAtPosition('result', { label: 'Knowledge Node', type: 'flashcards', id: 'sample' })}
                >
                  <Plus className="w-3.5 h-3.5" /> Result
                </Button>
                <div className="w-px h-4 bg-wax" />
                <Button 
                  className="h-10 px-6 gap-2 rounded-xl bg-bee-black hover:bg-bee-black/90 text-cream font-bold uppercase text-[10px] tracking-widest cursor-pointer shadow-lg shadow-bee-black/20"
                  onClick={() => {
                    playComplete();
                    toast.success('Generation pipeline active');
                  }}
                >
                  <Play className="w-3.5 h-3.5 fill-current" /> Run Flow
                </Button>
              </div>
            </Panel>

            <Panel position="bottom-left" className="mb-4 ml-4 flex flex-col gap-2">
              <div className="flex gap-1 p-1.5 bg-white/90 backdrop-blur-xl rounded-2xl border border-wax shadow-xl ring-1 ring-black/[0.03]">
                <Button variant="ghost" size="icon" className="w-10 h-10 rounded-xl hover:bg-honey/10 cursor-pointer" onClick={undo} title="Undo">
                  <Undo2 size={18} className="text-bee-black/60" />
                </Button>
                <Button variant="ghost" size="icon" className="w-10 h-10 rounded-xl hover:bg-honey/10 cursor-pointer" onClick={redo} title="Redo">
                  <Redo2 size={18} className="text-bee-black/60" />
                </Button>
                <div className="w-px h-6 bg-wax mx-1 self-center" />
                <Button variant="ghost" size="icon" className="w-10 h-10 rounded-xl hover:bg-honey/10 cursor-pointer" onClick={() => fitView()} title="Reset View">
                  <Maximize2 size={18} className="text-bee-black/60" />
                </Button>
              </div>
            </Panel>

            <Panel position="bottom-right" className="mb-4 mr-4 flex flex-col items-end gap-4">
              <MiniMap 
                nodeColor={(n) => {
                  if (n.type === 'process') return '#0F172A'
                  if (n.type === 'result') return '#FCD34F'
                  return '#FFF'
                }}
                className="!bg-white/80 !backdrop-blur-xl !border-wax !rounded-[1.5rem] !shadow-2xl !ring-1 !ring-black/[0.03] overflow-hidden"
                maskColor="rgba(255, 251, 235, 0.4)"
              />
              <Button 
                size="lg" 
                className="h-14 px-8 rounded-2xl bg-honey hover:bg-honey/90 text-bee-black font-bold uppercase text-[10px] tracking-[0.2em] shadow-2xl shadow-honey/20 transition-all active:scale-95 cursor-pointer border border-wax/50 group"
                onClick={() => {
                  playClick();
                  save();
                }}
              >
                <Save className="w-4 h-4 mr-2 group-hover:scale-110 transition-transform" /> Persist Architecture
              </Button>
            </Panel>

            <Controls showInteractive={false} className="!bg-white/90 !backdrop-blur-xl !border-wax !rounded-2xl !shadow-xl !m-0 !mt-20 !ml-4 !flex !flex-col !gap-1 !p-1 ring-1 ring-black/[0.03]" />
          </ReactFlow>
        </ContextMenuTrigger>
        <ContextMenuContent className="w-64 rounded-2xl border-wax p-2 bg-white/95 backdrop-blur-2xl shadow-2xl ring-1 ring-black/5">
          <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-bee-black/30">Architectural Suite</div>
          <ContextMenuSeparator className="bg-wax/50 mx-1" />
          <ContextMenuItem className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10" onClick={() => setIsUploadModalOpen(true)}>
            <div className="p-1.5 bg-honey/10 rounded-lg"><Upload size={14} className="text-honey" /></div>
            <div className="flex flex-col"><span className="text-sm font-bold text-bee-black">Ingest Asset</span><span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">External Data Node</span></div>
          </ContextMenuItem>
          <ContextMenuSub>
            <ContextMenuSubTrigger className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10">
              <div className="p-1.5 bg-bee-black/5 rounded-lg"><Plus size={14} className="text-bee-black/60" /></div>
              <div className="flex flex-col"><span className="text-sm font-bold text-bee-black">Synthesis Layer</span><span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Logic Operations</span></div>
            </ContextMenuSubTrigger>
            <ContextMenuSubContent className="w-56 rounded-xl border-wax bg-white/95 backdrop-blur-2xl p-1.5 shadow-2xl">
              <ContextMenuItem className="gap-3 rounded-lg py-2 px-3 cursor-pointer focus:bg-honey/10" onClick={() => addNodeAtPosition('process', { label: 'Synthesize', status: 'pending' })}>
                <Zap size={14} className="text-honey" /> <span className="text-xs font-bold uppercase tracking-wider">Fast Synthesis</span>
              </ContextMenuItem>
              <ContextMenuItem className="gap-3 rounded-lg py-2 px-3 cursor-pointer focus:bg-honey/10" onClick={() => addNodeAtPosition('process', { label: 'Categorize', status: 'pending' })}>
                <Layers size={14} className="text-bee-black/60" /> <span className="text-xs font-bold uppercase tracking-wider">Categorization</span>
              </ContextMenuItem>
            </ContextMenuSubContent>
          </ContextMenuSub>
          <ContextMenuSub>
            <ContextMenuSubTrigger className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10">
              <div className="p-1.5 bg-honey/10 rounded-lg"><Box size={14} className="text-honey" /></div>
              <div className="flex flex-col"><span className="text-sm font-bold text-bee-black">Knowledge Output</span><span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Artifact Synthesis</span></div>
            </ContextMenuSubTrigger>
            <ContextMenuSubContent className="w-56 rounded-xl border-wax bg-white/95 backdrop-blur-2xl p-1.5 shadow-2xl">
              <ContextMenuItem className="gap-3 rounded-lg py-2 px-3 cursor-pointer focus:bg-honey/10" onClick={() => addNodeAtPosition('result', { label: 'Flashcards', type: 'flashcards' })}>
                <Sparkles size={14} className="text-honey" /> <span className="text-xs font-bold uppercase tracking-wider">Flashcards</span>
              </ContextMenuItem>
              <ContextMenuItem className="gap-3 rounded-lg py-2 px-3 cursor-pointer focus:bg-honey/10" onClick={() => addNodeAtPosition('result', { label: 'Quiz Suite', type: 'quiz' })}>
                <MousePointer2 size={14} className="text-bee-black/60" /> <span className="text-xs font-bold uppercase tracking-wider">Quiz Suite</span>
              </ContextMenuItem>
            </ContextMenuSubContent>
          </ContextMenuSub>
          <ContextMenuSeparator className="bg-wax/50 mx-1" />
          <ContextMenuItem className="gap-3 rounded-xl py-3 px-4 text-red-600 focus:text-red-600 focus:bg-red-50 cursor-pointer" onClick={() => {
            useFlowStore.getState().setNodes([]);
            useFlowStore.getState().setEdges([]);
            takeSnapshot();
            playDelete();
          }}>
            <div className="p-1.5 bg-red-100 rounded-lg"><Trash2 size={14} /></div>
            <div className="flex flex-col"><span className="text-sm font-bold">Clear Pipeline</span><span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Destructive Action</span></div>
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>

      <AssetUploadModal 
        isOpen={isUploadModalOpen} 
        onClose={() => setIsUploadModalOpen(false)} 
        onUpload={handleAssetUpload}
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
