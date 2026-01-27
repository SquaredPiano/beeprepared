"use client";

import { Handle, Position, type NodeProps, useReactFlow } from "@xyflow/react";
import {
  FileText,
  Video,
  Music,
  Brain,
  HelpCircle,
  Layers,
  BookOpen,
  Presentation,
  ClipboardCheck,
  MoreVertical
} from "lucide-react";
import { motion } from "framer-motion";
import { NodeContextMenu } from "../NodeContextMenu";
import { useCanvasStore } from "@/store/useCanvasStore";

// Icon mapping for artifact types
const ARTIFACT_ICONS: Record<string, typeof FileText> = {
  video: Video,
  audio: Music,
  text: FileText,
  flat_text: FileText,
  knowledge_core: Brain,
  quiz: HelpCircle,
  flashcards: Layers,
  notes: BookOpen,
  slides: Presentation,
  exam: ClipboardCheck,
};

// Color mapping for artifact types
const ARTIFACT_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  video: { bg: "bg-purple-50", text: "text-purple-500", border: "border-purple-200" },
  audio: { bg: "bg-pink-50", text: "text-pink-500", border: "border-pink-200" },
  text: { bg: "bg-gray-50", text: "text-gray-500", border: "border-gray-200" },
  flat_text: { bg: "bg-green-50", text: "text-green-500", border: "border-green-200" },
  knowledge_core: { bg: "bg-amber-50", text: "text-amber-600", border: "border-amber-300" },
  quiz: { bg: "bg-blue-50", text: "text-blue-500", border: "border-blue-200" },
  flashcards: { bg: "bg-violet-50", text: "text-violet-500", border: "border-violet-200" },
  notes: { bg: "bg-emerald-50", text: "text-emerald-500", border: "border-emerald-200" },
  slides: { bg: "bg-orange-50", text: "text-orange-500", border: "border-orange-200" },
  exam: { bg: "bg-red-50", text: "text-red-500", border: "border-red-200" },
};

interface ArtifactNodeData {
  label: string;
  type: string;
  icon?: string;
  color?: string;
  artifact?: any;
  status?: "pending" | "running" | "completed" | "failed";
}

export function ArtifactNode({ id, data }: NodeProps & { id: string; data: ArtifactNodeData }) {
  const { setNodes, getNodes } = useReactFlow();
  const { takeSnapshot } = useCanvasStore();

  const handleDelete = () => {
    takeSnapshot();
    setNodes(getNodes().filter(n => n.id !== id));
  };

  const artifactType = data.type || "text";
  const Icon = ARTIFACT_ICONS[artifactType] || FileText;
  const colors = ARTIFACT_COLORS[artifactType] || ARTIFACT_COLORS.text;

  const isKnowledgeCore = artifactType === "knowledge_core";
  const isSource = ["video", "audio", "text"].includes(artifactType);

  return (
    <NodeContextMenu
      nodeType="artifact"
      onDelete={handleDelete}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className={`
          px-4 py-3 shadow-md rounded-xl bg-white min-w-[220px] group relative items-center flex gap-3
          border border-gray-100 hover:shadow-lg transition-all
          ${isKnowledgeCore ? "ring-1 ring-amber-200 bg-amber-50/10" : ""}
        `}
      >
        <div className={`
          p-2.5 rounded-lg shrink-0 
          ${isKnowledgeCore ? "bg-amber-100 text-amber-600" : "bg-gray-50 text-gray-600"}
        `}>
          <Icon className="w-4 h-4" />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <p className="text-[9px] font-bold uppercase tracking-widest text-gray-400 font-sans">
              {data.label || artifactType}
            </p>
            {data.status === "running" && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />}
          </div>

          <p className="text-sm font-semibold text-gray-900 truncate font-sans">
            {data.artifact?.content?.title || "Untitled Artifact"}
          </p>

          {isKnowledgeCore && (
            <p className="text-[9px] text-amber-600/60 font-medium font-sans mt-0.5">
              Knowledge Source
            </p>
          )}
        </div>

        {/* Status indicator (Failed) */}
        {data.status === "failed" && (
          <div className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full border-2 border-white" />
        )}

        {/* Input handle - only for non-source artifacts */}
        {!isSource && (
          <Handle
            type="target"
            position={Position.Left}
            className="w-2 h-2 bg-gray-300 border-2 border-white !-left-1"
          />
        )}

        {/* Output handle */}
        <Handle
          type="source"
          position={Position.Right}
          className={`w-2 h-2 border-2 border-white !-right-1 ${isKnowledgeCore ? "bg-amber-400" : "bg-gray-900"}`}
        />
      </motion.div>
    </NodeContextMenu>
  );
}
