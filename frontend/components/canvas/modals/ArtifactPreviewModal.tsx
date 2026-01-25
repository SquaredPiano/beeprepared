"use client";

import React from "react";
import { 
  Dialog, 
  DialogContent, 
} from "@/components/ui/dialog";
import { 
  Sparkles, 
  HelpCircle, 
  FileText, 
  Presentation,
  PlayCircle,
  Download,
  Share2,
  Trash2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface ArtifactPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  artifact: {
    label: string;
    type: 'flashcards' | 'quiz' | 'exam' | 'pptx' | string;
    count?: number;
    id: string;
  } | null;
}

export function ArtifactPreviewModal({ isOpen, onClose, artifact }: ArtifactPreviewModalProps) {
  if (!artifact) return null;

  const getIcon = () => {
    switch (artifact.type) {
      case 'flashcards': return Sparkles;
      case 'quiz': return HelpCircle;
      case 'exam': return FileText;
      case 'pptx': return Presentation;
      default: return Sparkles;
    }
  };

  const Icon = getIcon();

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl rounded-[32px] border-wax bg-cream/95 backdrop-blur-xl p-0 overflow-hidden shadow-2xl">
        <div className="p-12 flex flex-col items-center text-center">
          <div className="w-24 h-24 rounded-[2.5rem] bg-white shadow-xl flex items-center justify-center border border-wax mb-8 group hover:scale-110 transition-transform duration-500">
            <Icon size={40} className="text-honey-600 group-hover:rotate-12 transition-transform" />
          </div>

          <Badge className="bg-honey/10 text-honey-700 border-none uppercase text-[10px] tracking-[0.2em] px-4 py-1.5 font-bold mb-4">
            Synthesis Complete
          </Badge>

          <h2 className="text-3xl font-display uppercase tracking-tight text-bee-black mb-4">
            {artifact.label}
          </h2>

          <p className="text-sm text-bee-black/40 max-w-md leading-relaxed mb-12">
            Architectural synthesis of the knowledge core has finalized. 
            This artifact contains {artifact.count || 12} high-fidelity {artifact.type} units ready for ingestion.
          </p>

          <div className="grid grid-cols-2 gap-4 w-full">
            <Button 
              className="h-16 rounded-2xl bg-bee-black text-white hover:bg-honey-600 transition-all font-display text-xs uppercase tracking-widest font-bold group cursor-pointer"
              onClick={() => {
                // Navigate to practice
              }}
            >
              <PlayCircle className="mr-2 w-5 h-5 group-hover:scale-110 transition-transform" />
              Enter Practice
            </Button>
            <Button 
              variant="outline"
              className="h-16 rounded-2xl border-wax bg-white hover:bg-honey/10 transition-all font-display text-xs uppercase tracking-widest font-bold group cursor-pointer"
            >
              <Download className="mr-2 w-5 h-5 group-hover:-translate-y-1 transition-transform" />
              Export Units
            </Button>
          </div>
        </div>

        <div className="bg-bee-black/5 border-t border-wax p-6 flex justify-between items-center px-12">
          <div className="flex gap-4">
            <button className="text-[10px] font-bold uppercase tracking-widest text-bee-black/40 hover:text-bee-black transition-colors flex items-center gap-2 cursor-pointer">
              <Share2 size={14} /> Share
            </button>
          </div>
          <button className="text-[10px] font-bold uppercase tracking-widest text-red-600/40 hover:text-red-600 transition-colors flex items-center gap-2 cursor-pointer">
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
