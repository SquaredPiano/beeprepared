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
          px-4 py-3 shadow-xl rounded-2xl bg-white min-w-[200px] group relative
          border-2 ${colors.border}
          ${isKnowledgeCore ? "ring-2 ring-amber-300 ring-offset-2" : ""}
        `}
      >
        <div className="flex items-center gap-3">
          <div className={`p-2.5 rounded-xl ${colors.bg} ${colors.text} group-hover:scale-110 transition-transform duration-300`}>
            <Icon className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0">
            <p className={`text-[10px] font-bold uppercase tracking-widest ${colors.text}`}>
              {data.label || artifactType}
            </p>
            {data.artifact?.content?.title && (
              <p className="text-sm font-bold text-bee-black truncate mt-0.5">
                {data.artifact.content.title}
              </p>
            )}
            {isKnowledgeCore && data.artifact?.content?.concepts && (
              <p className="text-[10px] text-bee-black/40 mt-1">
                {data.artifact.content.concepts.length} concepts
              </p>
            )}
          </div>
          <button className="text-bee-black/20 hover:text-bee-black transition-colors opacity-0 group-hover:opacity-100">
            <MoreVertical className="w-4 h-4" />
          </button>
        </div>
        
        {/* Status indicator */}
        {data.status && data.status !== "completed" && (
          <div className="absolute -top-2 -right-2">
            <span className={`
              px-2 py-0.5 rounded-full text-[8px] font-bold uppercase
              ${data.status === "pending" ? "bg-gray-100 text-gray-500" : ""}
              ${data.status === "running" ? "bg-blue-100 text-blue-600 animate-pulse" : ""}
              ${data.status === "failed" ? "bg-red-100 text-red-600" : ""}
            `}>
              {data.status}
            </span>
          </div>
        )}
        
        {/* Input handle - only for non-source artifacts */}
        {!isSource && (
          <Handle 
            type="target" 
            position={Position.Left} 
            className="w-3 h-3 bg-wax border-2 border-white !-left-1.5"
          />
        )}
        
        {/* Output handle */}
        <Handle 
          type="source" 
          position={Position.Right} 
          className={`w-3 h-3 border-2 border-white !-right-1.5 ${isKnowledgeCore ? "bg-amber-500" : "bg-honey"}`}
        />
      </motion.div>
    </NodeContextMenu>
  );
}
