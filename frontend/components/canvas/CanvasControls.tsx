"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import { 
  Plus, 
  Minus, 
  Maximize2, 
  Lock, 
  Unlock, 
  Undo2, 
  Redo2,
  Map
} from "lucide-react";
import { useCanvasStore } from "@/store/useCanvasStore";
import { useReactFlow } from "@xyflow/react";
import { cn } from "@/lib/utils";

export function CanvasControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const { 
    isLocked, 
    setIsLocked, 
    undo, 
    redo, 
    historyIndex, 
    history,
    showMiniMap,
    setShowMiniMap
  } = useCanvasStore();

  const canUndo = historyIndex > 0;
  const canRedo = historyIndex < history.length - 1;

  return (
    <div className="absolute bottom-8 right-8 flex flex-col gap-4 z-50">
      {/* Zoom & Lock Controls */}
      <div className="flex flex-col p-1.5 bg-white/90 backdrop-blur-xl rounded-[20px] border border-wax shadow-2xl ring-1 ring-black/5">
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => zoomIn()} 
          className="w-10 h-10 rounded-xl hover:bg-honey/10 cursor-pointer"
          title="Zoom In"
        >
          <Plus size={18} className="text-bee-black/60" />
        </Button>
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => zoomOut()} 
          className="w-10 h-10 rounded-xl hover:bg-honey/10 cursor-pointer"
          title="Zoom Out"
        >
          <Minus size={18} className="text-bee-black/60" />
        </Button>
        <div className="w-full h-px bg-wax my-1" />
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => fitView()} 
          className="w-10 h-10 rounded-xl hover:bg-honey/10 cursor-pointer"
          title="Fit View"
        >
          <Maximize2 size={18} className="text-bee-black/60" />
        </Button>
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => setShowMiniMap(!showMiniMap)} 
          className={cn(
            "w-10 h-10 rounded-xl transition-all cursor-pointer",
            showMiniMap ? "bg-honey text-bee-black" : "hover:bg-honey/10 text-bee-black/60"
          )}
          title={showMiniMap ? "Hide Mini Map" : "Show Mini Map"}
        >
          <Map size={18} />
        </Button>
        <div className="w-full h-px bg-wax my-1" />
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={() => setIsLocked(!isLocked)} 
          className={cn(
            "w-10 h-10 rounded-xl transition-all cursor-pointer",
            isLocked ? "bg-honey text-bee-black" : "hover:bg-honey/10 text-bee-black/60"
          )}
          title={isLocked ? "Unlock Canvas" : "Lock Canvas"}
        >
          {isLocked ? <Lock size={18} /> : <Unlock size={18} />}
        </Button>
      </div>
      
      {/* History Controls */}
      <div className="flex p-1.5 bg-white/90 backdrop-blur-xl rounded-[20px] border border-wax shadow-2xl ring-1 ring-black/5">
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={undo} 
          disabled={!canUndo}
          className="w-10 h-10 rounded-xl hover:bg-honey/10 disabled:opacity-30 cursor-pointer"
          title="Undo"
        >
          <Undo2 size={18} className="text-bee-black/60" />
        </Button>
        <Button 
          variant="ghost" 
          size="icon" 
          onClick={redo} 
          disabled={!canRedo}
          className="w-10 h-10 rounded-xl hover:bg-honey/10 disabled:opacity-30 cursor-pointer"
          title="Redo"
        >
          <Redo2 size={18} className="text-bee-black/60" />
        </Button>
      </div>
    </div>
  );
}
