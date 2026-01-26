"use client";

import { Handle, Position, type NodeProps, useReactFlow } from "@xyflow/react";
import {
  BookOpen,
  HelpCircle,
  Layers,
  Presentation,
  ClipboardCheck,
  Play,
  RefreshCw,
  Loader2,
  Check,
  AlertCircle,
  Eye
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useState, useCallback, useEffect } from "react";
import { NodeContextMenu } from "../NodeContextMenu";
import { useCanvasStore } from "@/store/useCanvasStore";
import { ArtifactPreviewModal } from "../modals/ArtifactPreviewModal";
import { useArtifactGenerator, TargetType, findKnowledgeCore } from "@/hooks/useArtifactGenerator";
import { Artifact } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

// Icon mapping for generator types
const GENERATOR_ICONS: Record<string, typeof BookOpen> = {
  notes: BookOpen,
  quiz: HelpCircle,
  flashcards: Layers,
  slides: Presentation,
  exam: ClipboardCheck,
};

// Color mapping for generator types
const GENERATOR_COLORS: Record<string, { bg: string; text: string; border: string; accent: string }> = {
  notes: { bg: "bg-emerald-50", text: "text-emerald-600", border: "border-emerald-200", accent: "bg-emerald-500" },
  quiz: { bg: "bg-blue-50", text: "text-blue-600", border: "border-blue-200", accent: "bg-blue-500" },
  flashcards: { bg: "bg-violet-50", text: "text-violet-600", border: "border-violet-200", accent: "bg-violet-500" },
  slides: { bg: "bg-orange-50", text: "text-orange-600", border: "border-orange-200", accent: "bg-orange-500" },
  exam: { bg: "bg-red-50", text: "text-red-600", border: "border-red-200", accent: "bg-red-500" },
};

const GENERATOR_LABELS: Record<string, string> = {
  notes: "Study Notes",
  quiz: "Practice Quiz",
  flashcards: "Flashcards",
  slides: "Presentation",
  exam: "Mock Exam",
};

export interface GeneratorNodeData {
  label?: string;
  subType: TargetType; // quiz, notes, slides, flashcards, exam
  status?: "idle" | "pending" | "running" | "completed" | "failed";
  artifact?: Artifact | null;
  progress?: number;
  error?: string | null;
  [key: string]: unknown; // Index signature for @xyflow/react compatibility
}

interface GeneratorNodeProps {
  id: string;
  data: GeneratorNodeData;
}

export function GeneratorNode({ id, data }: GeneratorNodeProps) {
  const { setNodes, getNodes, getEdges } = useReactFlow();
  const { takeSnapshot, currentProjectId, refreshArtifacts } = useCanvasStore();
  const { states, generate, cancel } = useArtifactGenerator();

  const [showPreview, setShowPreview] = useState(false);
  const [localArtifact, setLocalArtifact] = useState<Artifact | null>(data.artifact || null);

  const generatorType = data.subType || "notes";
  const Icon = GENERATOR_ICONS[generatorType] || BookOpen;
  const colors = GENERATOR_COLORS[generatorType] || GENERATOR_COLORS.notes;
  const label = data.label || GENERATOR_LABELS[generatorType] || generatorType;

  // Get current state from hook
  const generatorState = states[generatorType];
  const status = data.status || generatorState?.status || "idle";
  const progress = data.progress || generatorState?.progress || 0;
  const error = data.error || generatorState?.error;

  // Sync artifact from generator state
  useEffect(() => {
    if (generatorState?.artifact) {
      setLocalArtifact(generatorState.artifact);
      updateNodeData({ artifact: generatorState.artifact, status: "completed" });
    }
  }, [generatorState?.artifact]);

  // Update node data helper
  const updateNodeData = useCallback((updates: Partial<GeneratorNodeData>) => {
    setNodes(nodes =>
      nodes.map(n =>
        n.id === id
          ? { ...n, data: { ...n.data, ...updates } }
          : n
      )
    );
  }, [id, setNodes]);

  // Find connected sources (Knowledge Core, Asset, or Chained Generators)
  const findSourceArtifacts = useCallback(async (): Promise<string[]> => {
    // 1. Check incoming edges
    const edges = getEdges();
    const nodes = getNodes();

    const incomingEdges = edges.filter(e => e.target === id);
    console.log(`[Generator ${id}] Finding sources. Incoming edges:`, incomingEdges.length);

    if (incomingEdges.length === 0) {
      // Fallback: Find any valid source in the project (Single Input logic fallback)
      if (currentProjectId) {
        const core = await findKnowledgeCore(currentProjectId);
        if (core) {
          console.log(`[Generator ${id}] Fallback: using project knowledge core:`, core.id);
          return [core.id];
        }
      }
      return [];
    }

    const foundIds: string[] = [];

    for (const edge of incomingEdges) {
      const sourceNode = nodes.find(n => n.id === edge.source);
      if (!sourceNode) continue;

      console.log(`[Generator ${id}] Checking source node:`, sourceNode.type, sourceNode.id);

      // Case A: Connected to Knowledge Core direct
      if (sourceNode.type === 'artifactNode' && sourceNode.data?.type === 'knowledge_core') {
        if ((sourceNode.data.artifact as { id: string })?.id) {
          foundIds.push((sourceNode.data.artifact as { id: string }).id);
        }
      }
      // Case B: Connected to Generator (Chaining)
      else if (sourceNode.type === 'generator') {
        const parentData = sourceNode.data as unknown as GeneratorNodeData;
        if (parentData.artifact && (parentData.artifact as { id: string }).id) {
          foundIds.push((parentData.artifact as { id: string }).id);
        } else {
          // If parent incomplete, we skip it but log warning
          console.warn(`[Generator ${id}] Skipping incomplete parent generator ${sourceNode.id}`);
        }
      }
      // Case C: Asset -> Project Knowledge Core
      else if (sourceNode.type === 'asset') {
        if (currentProjectId) {
          const core = await findKnowledgeCore(currentProjectId);
          if (core) {
            foundIds.push(core.id);
          }
        }
      }
    }

    // Deduplicate
    return Array.from(new Set(foundIds));
  }, [getEdges, getNodes, id, currentProjectId]);

  // Handle generation
  const handleGenerate = useCallback(async () => {
    if (!currentProjectId) {
      toast.error("No project selected", { description: "Save your project first" });
      return;
    }

    const sourceArtifactIds = await findSourceArtifacts();

    if (sourceArtifactIds.length === 0) {
      toast.error("No Source found", {
        description: "Connect to a source file or knowledge core to generate.",
      });
      return;
    }

    updateNodeData({ status: "pending", progress: 0, error: null });

    // Pass IDs list to generate
    const result = await generate(currentProjectId, sourceArtifactIds, generatorType);

    if (result) {
      setLocalArtifact(result);
      updateNodeData({
        status: "completed",
        artifact: result,
        progress: 100
      });

      // Refresh canvas artifacts to sync
      await refreshArtifacts();
    } else if (generatorState?.error) {
      updateNodeData({
        status: "failed",
        error: generatorState.error,
        progress: 0
      });
    }
  }, [currentProjectId, findSourceArtifacts, generate, generatorType, updateNodeData, refreshArtifacts, generatorState?.error]);

  // Handle cancel
  const handleCancel = useCallback(() => {
    cancel(generatorType);
    updateNodeData({ status: "idle", progress: 0 });
  }, [cancel, generatorType, updateNodeData]);

  // Handle delete
  const handleDelete = useCallback(() => {
    takeSnapshot();
    setNodes(getNodes().filter(n => n.id !== id));
  }, [takeSnapshot, setNodes, getNodes, id]);

  // Status-based rendering
  const isGenerating = status === "pending" || status === "running";
  const isCompleted = status === "completed" && localArtifact;
  const isFailed = status === "failed";

  return (
    <>
      <NodeContextMenu
        nodeType="result"
        onDelete={handleDelete}
        onPractice={isCompleted ? () => setShowPreview(true) : undefined}
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          className={`
            shadow-xl rounded-2xl bg-white min-w-[220px] group relative
            border-2 ${isCompleted ? colors.border : isFailed ? "border-red-300" : "border-wax"}
            transition-all duration-300
          `}
        >
          {/* Content Wrapper - Handles clipping for corners */}
          <div className="w-full h-full rounded-[14px] overflow-hidden relative bg-inherit"> {/* radius slightly less than parent 2xl (16px) - 2px border */}
            {/* Progress bar */}
            {isGenerating && (
              <motion.div
                className={`absolute top-0 left-0 h-1 ${colors.accent}`}
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.3 }}
              />
            )}

            <div className="px-4 py-3">
              <div className="flex items-center gap-3">
                <div className={`
                    p-2.5 rounded-xl transition-all duration-300
                    ${isCompleted ? colors.bg : isFailed ? "bg-red-50" : "bg-cream"}
                    ${isGenerating ? "animate-pulse" : ""}
                  `}>
                  {isGenerating ? (
                    <Loader2 className={`w-5 h-5 ${colors.text} animate-spin`} />
                  ) : isCompleted ? (
                    <Check className="w-5 h-5 text-green-500" />
                  ) : isFailed ? (
                    <AlertCircle className="w-5 h-5 text-red-500" />
                  ) : (
                    <Icon className={`w-5 h-5 ${colors.text}`} />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-[10px] font-bold uppercase tracking-widest ${colors.text}`}>
                    {isGenerating ? "Generating..." : isCompleted ? "Ready" : isFailed ? "Failed" : "Generator"}
                  </p>
                  <p className="text-sm font-bold text-bee-black truncate">{label}</p>
                </div>
              </div>

              {/* Error message */}
              {isFailed && error && (
                <p className="text-xs text-red-500 mt-2 truncate" title={error}>
                  {error}
                </p>
              )}

              {/* Action buttons */}
              <div className="mt-3 pt-3 border-t border-wax flex gap-2">
                {isGenerating ? (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleCancel}
                    className="flex-1 h-8 text-[10px] uppercase tracking-widest font-bold"
                  >
                    Cancel
                  </Button>
                ) : isCompleted ? (
                  <>
                    <Button
                      size="sm"
                      onClick={() => setShowPreview(true)}
                      className={`flex-1 h-8 text-[10px] uppercase tracking-widest font-bold ${colors.accent} text-white hover:opacity-90`}
                    >
                      <Eye className="w-3 h-3 mr-1" /> View
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleGenerate}
                      className="h-8 px-2"
                      title="Regenerate"
                    >
                      <RefreshCw className="w-3 h-3" />
                    </Button>
                  </>
                ) : (
                  <Button
                    size="sm"
                    onClick={handleGenerate}
                    className={`flex-1 h-8 text-[10px] uppercase tracking-widest font-bold ${colors.accent} text-white hover:opacity-90`}
                  >
                    <Play className="w-3 h-3 mr-1" /> Generate
                  </Button>
                )}
              </div>
            </div>
          </div>

          {/* Input handle - Outside wrapper to avoid clipping */}
          <Handle
            type="target"
            position={Position.Left}
            className={`w-3 h-3 border-2 border-white !-left-1.5 ${isCompleted ? colors.accent : "bg-wax"}`}
          />

          {/* Output handle - Outside wrapper */}
          <Handle
            type="source"
            position={Position.Right}
            className={`w-3 h-3 border-2 border-white !-right-1.5 ${isCompleted ? "bg-honey" : "bg-wax"}`}
          />
        </motion.div>
      </NodeContextMenu>

      {/* Preview Modal */}
      <ArtifactPreviewModal
        isOpen={showPreview}
        onClose={() => setShowPreview(false)}
        artifact={localArtifact}
        onRegenerate={handleGenerate}
        isRegenerating={isGenerating}
      />
    </>
  );
}
