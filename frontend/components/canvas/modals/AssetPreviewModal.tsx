"use client";

import React from "react";
import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle 
} from "@/components/ui/dialog";
import { 
  FileText, 
  Video, 
  Presentation, 
  Download,
  ExternalLink,
  Clock,
  HardDrive
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface AssetPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  asset: {
    label: string;
    type: 'pdf' | 'video' | 'pptx' | string;
    size?: string;
    date?: string;
    url?: string;
  } | null;
}

export function AssetPreviewModal({ isOpen, onClose, asset }: AssetPreviewModalProps) {
  if (!asset) return null;

  const Icon = asset.type === 'pdf' ? FileText : asset.type === 'video' ? Video : Presentation;

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-3xl rounded-[32px] border-wax bg-cream/95 backdrop-blur-xl p-0 overflow-hidden shadow-2xl">
        <div className="relative aspect-video bg-bee-black/5 flex items-center justify-center border-b border-wax">
          {asset.type === 'video' ? (
            <div className="w-full h-full flex items-center justify-center">
              <Video size={64} className="text-bee-black/10 animate-pulse" />
              <p className="absolute bottom-8 text-[10px] font-bold uppercase tracking-widest text-bee-black/40">
                Media Relay Pending Integration
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4">
              <div className="w-20 h-20 rounded-[2rem] bg-white shadow-xl flex items-center justify-center border border-wax">
                <Icon size={32} className="text-honey-600" />
              </div>
              <Badge className="bg-honey text-bee-black border-none uppercase text-[9px] tracking-widest px-3 py-1 font-bold">
                {asset.type} Protocol
              </Badge>
            </div>
          )}
        </div>

        <div className="p-8">
          <div className="flex justify-between items-start mb-8">
            <div>
              <h2 className="text-2xl font-display uppercase tracking-tight text-bee-black mb-2">
                {asset.label}
              </h2>
              <div className="flex gap-6">
                <div className="flex items-center gap-2 text-bee-black/40">
                  <HardDrive size={14} />
                  <span className="text-[10px] font-bold uppercase tracking-widest">{asset.size || "12.4 MB"}</span>
                </div>
                <div className="flex items-center gap-2 text-bee-black/40">
                  <Clock size={14} />
                  <span className="text-[10px] font-bold uppercase tracking-widest">{asset.date || "Today, 14:20"}</span>
                </div>
              </div>
            </div>
            
            <div className="flex gap-2">
              <Button variant="outline" className="rounded-xl border-wax h-12 px-6 font-bold uppercase text-[10px] tracking-widest hover:bg-honey transition-all cursor-pointer">
                <Download size={14} className="mr-2" /> Download
              </Button>
              <Button className="rounded-xl bg-bee-black text-white h-12 px-6 font-bold uppercase text-[10px] tracking-widest hover:bg-honey-600 transition-all cursor-pointer">
                <ExternalLink size={14} className="mr-2" /> Open Source
              </Button>
            </div>
          </div>

          <div className="bg-honey/5 border border-honey/10 rounded-2xl p-6">
            <h4 className="text-[10px] font-bold uppercase tracking-widest text-honey-700 mb-3">Logical Connections</h4>
            <p className="text-sm text-honey-900/60 leading-relaxed">
              This asset is currently serving as the primary knowledge source for the active pipeline. 
              Downstream synthesis layers are extracting core concepts based on architectural constraints.
            </p>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
