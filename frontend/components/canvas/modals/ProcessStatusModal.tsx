"use client";

import React from "react";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import {
  Activity,
  CheckCircle2,
  Circle,
  Loader2,
  ShieldCheck,
  Zap,
  Box,
  Layers
} from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

interface ProcessStatusModalProps {
  isOpen: boolean;
  onClose: () => void;
  process: {
    label: string;
    status: 'pending' | 'processing' | 'complete' | 'error';
    progress: number;
    stage: string;
  } | null;
}

const stages = [
  { id: 'extraction', label: 'Neural Extraction', icon: Zap },
  { id: 'cleaning', label: 'Logical Normalization', icon: Box },
  { id: 'synthesis', label: 'Atomic Synthesis', icon: Layers },
  { id: 'validation', label: 'Architectural Validation', icon: ShieldCheck },
];

export function ProcessStatusModal({ isOpen, onClose, process }: ProcessStatusModalProps) {
  if (!process) return null;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-xl rounded-[32px] border-wax bg-cream/95 backdrop-blur-xl p-8 shadow-2xl overflow-hidden">
        <div className="flex items-center gap-4 mb-8">
          <div className="w-12 h-12 rounded-2xl bg-honey/10 flex items-center justify-center border border-honey/20">
            <Activity className={cn("text-honey-600", process.status === 'processing' && "animate-pulse")} size={24} />
          </div>
          <div>
            <h2 className="text-xl font-display uppercase tracking-tight text-bee-black">
              Pipeline Status: {process.label}
            </h2>
            <p className="text-[10px] font-bold uppercase tracking-widest text-bee-black/30">
              Real-time Ingestion Metrics
            </p>
          </div>
        </div>

        <div className="space-y-8">
          <div className="space-y-3">
            <div className="flex justify-between text-[10px] font-bold uppercase tracking-widest">
              <span className="text-bee-black/40">Collective Progress</span>
              <span className="text-honey-600">{process.progress}%</span>
            </div>
            <Progress value={process.progress} className="h-2 bg-bee-black/5" />
          </div>

          <div className="grid grid-cols-1 gap-3">
            {stages.map((stage, idx) => {
              const isActive = process.stage === stage.id || (process.status === 'complete');
              const isPending = !isActive && process.status !== 'complete';
              const Icon = stage.icon;

              return (
                <div
                  key={stage.id}
                  className={cn(
                    "flex items-center gap-4 p-4 rounded-2xl border transition-all",
                    isActive ? "bg-white border-honey shadow-sm scale-[1.02]" : "bg-white/40 border-wax opacity-50"
                  )}
                >
                  <div className={cn(
                    "w-10 h-10 rounded-xl flex items-center justify-center",
                    isActive ? "bg-honey/10 text-honey-600" : "bg-bee-black/5 text-bee-black/20"
                  )}>
                    <Icon size={20} />
                  </div>
                  <div className="flex-1">
                    <h4 className="text-xs font-bold uppercase tracking-wide text-bee-black">
                      {stage.label}
                    </h4>
                    <p className="text-[9px] font-bold opacity-40 uppercase tracking-widest mt-0.5">
                      {isActive ? "Active Layer" : "Queued"}
                    </p>
                  </div>
                  {isActive && process.status !== 'complete' && <Loader2 size={16} className="animate-spin text-honey" />}
                  {isActive && process.status === 'complete' && <CheckCircle2 size={16} className="text-green-500" />}
                </div>
              );
            })}
          </div>

          <div className="p-4 rounded-2xl bg-bee-black text-white/90 text-[10px] font-mono leading-relaxed">
            <p className="opacity-40 mb-1 font-bold uppercase tracking-widest">Architectural Logs</p>
            <p>&gt; initializing neural foragers...</p>
            <p>&gt; stream established at 14.2 MB/s</p>
            {process.status === 'complete' && <p className="text-honey-400">&gt; synthesis complete. artifacts ready.</p>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
