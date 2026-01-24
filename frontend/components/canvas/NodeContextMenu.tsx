"use client";

import React from "react";
import { 
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubTrigger,
  ContextMenuSubContent
} from "@/components/ui/context-menu";
import { 
  Eye, 
  Trash2, 
  Unlink, 
  RefreshCw, 
  Download, 
  PlayCircle,
  Activity
} from "lucide-react";
import { cn } from "@/lib/utils";

interface NodeContextMenuProps {
  children: React.ReactNode;
  nodeType: 'asset' | 'process' | 'result';
  onPreview?: () => void;
  onDelete?: () => void;
  onDisconnect?: () => void;
  onRerun?: () => void;
  onDownload?: () => void;
  onPractice?: () => void;
}

export function NodeContextMenu({
  children,
  nodeType,
  onPreview,
  onDelete,
  onDisconnect,
  onRerun,
  onDownload,
  onPractice
}: NodeContextMenuProps) {
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent className="w-64 rounded-2xl border-wax bg-white/95 backdrop-blur-2xl p-2 shadow-2xl ring-1 ring-black/5">
        <div className="px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-bee-black/30">
          Node Operations
        </div>
        <ContextMenuSeparator className="bg-wax/50 mx-1" />
        
        {onPreview && (
          <ContextMenuItem className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10" onClick={onPreview}>
            <div className="p-1.5 bg-honey/10 rounded-lg"><Eye size={14} className="text-honey" /></div>
            <div className="flex flex-col">
              <span className="text-sm font-bold text-bee-black">View Details</span>
              <span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Inspection Protocol</span>
            </div>
          </ContextMenuItem>
        )}

        {nodeType === 'process' && onRerun && (
          <ContextMenuItem className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10" onClick={onRerun}>
            <div className="p-1.5 bg-blue-50 rounded-lg"><RefreshCw size={14} className="text-blue-600" /></div>
            <div className="flex flex-col">
              <span className="text-sm font-bold text-bee-black">Re-synthesize</span>
              <span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Trigger Extraction</span>
            </div>
          </ContextMenuItem>
        )}

        {nodeType === 'result' && (
          <>
            {onPractice && (
              <ContextMenuItem className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10" onClick={onPractice}>
                <div className="p-1.5 bg-green-50 rounded-lg"><PlayCircle size={14} className="text-green-600" /></div>
                <div className="flex flex-col">
                  <span className="text-sm font-bold text-bee-black">Enter Practice</span>
                  <span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Knowledge Drill</span>
                </div>
              </ContextMenuItem>
            )}
            {onDownload && (
              <ContextMenuItem className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10" onClick={onDownload}>
                <div className="p-1.5 bg-indigo-50 rounded-lg"><Download size={14} className="text-indigo-600" /></div>
                <div className="flex flex-col">
                  <span className="text-sm font-bold text-bee-black">Export Artifact</span>
                  <span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Local Persistence</span>
                </div>
              </ContextMenuItem>
            )}
          </>
        )}

        <ContextMenuSeparator className="bg-wax/50 mx-1" />
        
        {onDisconnect && (
          <ContextMenuItem className="gap-3 rounded-xl py-3 px-4 cursor-pointer focus:bg-honey/10" onClick={onDisconnect}>
            <div className="p-1.5 bg-bee-black/5 rounded-lg"><Unlink size={14} className="text-bee-black/60" /></div>
            <div className="flex flex-col">
              <span className="text-sm font-bold text-bee-black">Sever All Links</span>
              <span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Logical Disconnect</span>
            </div>
          </ContextMenuItem>
        )}

        {onDelete && (
          <ContextMenuItem 
            className="gap-3 rounded-xl py-3 px-4 text-red-600 focus:text-red-600 focus:bg-red-50 cursor-pointer" 
            onClick={onDelete}
          >
            <div className="p-1.5 bg-red-100 rounded-lg"><Trash2 size={14} /></div>
            <div className="flex flex-col">
              <span className="text-sm font-bold">Decommission</span>
              <span className="text-[9px] font-bold opacity-40 uppercase tracking-widest leading-none mt-1">Permanent Removal</span>
            </div>
          </ContextMenuItem>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}
