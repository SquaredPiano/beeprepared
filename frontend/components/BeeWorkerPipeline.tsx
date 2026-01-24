"use client";

import React, { useMemo } from "react";
import {
  ReactFlow,
  Background,
  useNodesState,
  useEdgesState,
  NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { WorkerNode } from "./WorkerNode";
import { FileText, Search, LayoutGrid, Sparkles, CheckCircle } from "lucide-react";

const nodeTypes: NodeTypes = {
  worker: WorkerNode,
};

const initialNodes = [
  {
    id: "1",
    type: "worker",
    position: { x: 0, y: 100 },
    data: {
      label: "Ingest",
      icon: FileText,
      status: "completed",
      description: "Artifact Absorption",
    },
  },
  {
    id: "2",
    type: "worker",
    position: { x: 300, y: 100 },
    data: {
      label: "Extract",
      icon: Search,
      status: "processing",
      description: "Nectar Retrieval",
    },
  },
  {
    id: "3",
    type: "worker",
    position: { x: 600, y: 0 },
    data: {
      label: "Categorize",
      icon: LayoutGrid,
      status: "idle",
      description: "Cell Organization",
    },
  },
  {
    id: "4",
    type: "worker",
    position: { x: 600, y: 200 },
    data: {
      label: "Generate",
      icon: Sparkles,
      status: "idle",
      description: "Honey Production",
    },
  },
  {
    id: "5",
    type: "worker",
    position: { x: 900, y: 100 },
    data: {
      label: "Finalize",
      icon: CheckCircle,
      status: "idle",
      description: "Seal the Hive",
    },
  },
];

const initialEdges = [
  { id: "e1-2", source: "1", target: "2", animated: true, style: { stroke: "#F59E0B" } },
  { id: "e2-3", source: "2", target: "3", animated: false, style: { stroke: "#E2E2E2" } },
  { id: "e2-4", source: "2", target: "4", animated: false, style: { stroke: "#E2E2E2" } },
  { id: "e3-5", source: "3", target: "5", animated: false, style: { stroke: "#E2E2E2" } },
  { id: "e4-5", source: "4", target: "5", animated: false, style: { stroke: "#E2E2E2" } },
];

export function BeeWorkerPipeline() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState(initialEdges);

  return (
    <div className="w-full h-[500px] glass rounded-2xl border border-border/40 overflow-hidden honey-glow">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        fitView
        className="bg-transparent"
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background color="#F59E0B" gap={20} size={1} opacity={0.05} />
      </ReactFlow>
    </div>
  );
}
