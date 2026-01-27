"use client";

import React, { useCallback, useMemo } from "react";
import { 
  ReactFlow, 
  Background, 
  Controls, 
  BackgroundVariant, 
  NodeTypes, 
  useNodesState, 
  useEdgesState,
  ConnectionMode,
  Node,
  Edge
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { BeeNode } from "./BeeNode";
import { 
  FileText, 
  Search, 
  Sparkles, 
  Workflow,
  Archive,
  Cpu
} from "lucide-react";

const nodeTypes: NodeTypes = {
  bee: BeeNode,
};

const initialNodes: Node[] = [
  {
    id: "ingest",
    type: "bee",
    position: { x: 0, y: 0 },
    data: { 
      label: "Ingestion", 
      beeType: "Forager",
      description: "Collecting artifacts", 
      icon: FileText,
      status: "completed"
    },
  },
  {
    id: "analyze",
    type: "bee",
    position: { x: 350, y: -50 },
    data: { 
      label: "Analysis", 
      beeType: "Transcriber",
      description: "Extracting essence", 
      icon: Search,
      status: "processing"
    },
  },
  {
    id: "synthesize",
    type: "bee",
    position: { x: 700, y: 50 },
    data: { 
      label: "Synthesis", 
      beeType: "Extractor",
      description: "Structuring knowledge", 
      icon: Cpu,
      status: "pending"
    },
  },
  {
    id: "organize",
    type: "bee",
    position: { x: 1050, y: 0 },
    data: { 
      label: "Artifacts", 
      beeType: "Builder",
      description: "Finalizing library", 
      icon: Archive,
      status: "pending"
    },
  },
];

const initialEdges: Edge[] = [
  { 
    id: "e1-2", 
    source: "ingest", 
    target: "analyze", 
    animated: true,
    style: { stroke: "#F59E0B", strokeWidth: 3 }
  },
  { 
    id: "e2-3", 
    source: "analyze", 
    target: "synthesize", 
    animated: true,
    style: { stroke: "#F59E0B", strokeWidth: 3 }
  },
  { 
    id: "e3-4", 
    source: "synthesize", 
    target: "organize", 
    animated: true,
    style: { stroke: "#F59E0B", strokeWidth: 3 }
  },
];

interface FlowCanvasProps {
  currentStage?: string;
  progress?: number;
}

export function FlowCanvas({ currentStage, progress }: FlowCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Update nodes based on currentStage
  React.useEffect(() => {
    setNodes((nds) => 
      nds.map((node) => {
        let status: "pending" | "processing" | "completed" = "pending";
        
        // Simple mapping logic
        const stages = ["ingest", "analyze", "synthesize", "organize"];
        const stageIndex = stages.indexOf(node.id);
        const currentStageStr = currentStage?.toLowerCase() || "";
        
        let currentIndex = -1;
        if (currentStageStr.includes("ingest") || currentStageStr.includes("upload")) currentIndex = 0;
        else if (currentStageStr.includes("analyze") || currentStageStr.includes("transcribe")) currentIndex = 1;
        else if (currentStageStr.includes("synthesize") || currentStageStr.includes("extract")) currentIndex = 2;
        else if (currentStageStr.includes("organize") || currentStageStr.includes("generate")) currentIndex = 3;
        
        if (stageIndex < currentIndex) status = "completed";
        else if (stageIndex === currentIndex) status = "processing";
        
        return {
          ...node,
          data: { ...node.data, status }
        };
      })
    );
  }, [currentStage, setNodes]);

  return (
    <div className="w-full h-full min-h-[600px] rounded-[40px] overflow-hidden border border-border/40 bg-stone-50/30 backdrop-blur-xl relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        connectionMode={ConnectionMode.Loose}
        fitView
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          style: { stroke: "#F59E0B", strokeWidth: 3 },
          animated: true,
        }}
      >
        <Background 
          variant={BackgroundVariant.Lines} 
          gap={60} 
          size={1} 
          color="#F59E0B" 
          className="opacity-5"
        />
        <Controls 
          showInteractive={false} 
          className="!bg-white/80 !backdrop-blur-md !border-border/40 !rounded-2xl !shadow-2xl [&>button]:!bg-transparent [&>button]:!rounded-xl [&>button]:!border-none [&>button]:!w-12 [&>button]:!h-12 [&>button]:hover:!bg-honey-50 [&>button]:!text-bee-black transition-all"
        />
      </ReactFlow>
      
      {/* HUD Overlay */}
      <div className="absolute top-10 left-10 flex items-center gap-6 pointer-events-none">
        <div className="w-14 h-14 bg-bee-black rounded-2xl flex items-center justify-center shadow-2xl">
          <Workflow className="w-6 h-6 text-honey-500 animate-spin-slow" />
        </div>
        <div className="space-y-1">
          <div className="text-sm font-display uppercase tracking-[0.2em] font-bold">Hive Pipeline</div>
          <div className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-honey-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-honey-500"></span>
            </span>
            <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold opacity-60">Synchronized with Collective Intelligence</span>
          </div>
        </div>
      </div>
    </div>
  );
}
