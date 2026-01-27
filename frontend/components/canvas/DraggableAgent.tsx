"use client";

import React from "react";
import { motion } from "framer-motion";
import { GripVertical } from "lucide-react";
import { cn } from "@/lib/utils";
import { 
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface DraggableAgentProps {
  type: string;
  subType?: string;
  label: string;
  description: string;
  icon: any;
  color: "blue" | "green" | "purple" | "honey" | "orange" | "red" | "indigo";
  collapsed?: boolean;
  disabled?: boolean;
  tooltip?: string;
}

const colorClasses = {
  blue: "from-blue-500/10 to-blue-500/5 border-blue-500/20 text-blue-600",
  green: "from-green-500/10 to-green-500/5 border-green-500/20 text-green-600",
  purple: "from-purple-500/10 to-purple-500/5 border-purple-500/20 text-purple-600",
  honey: "from-honey-500/10 to-honey-500/5 border-honey-500/20 text-honey-600",
  orange: "from-orange-500/10 to-orange-500/5 border-orange-500/20 text-orange-600",
  red: "from-red-500/10 to-red-500/5 border-red-500/20 text-red-600",
  indigo: "from-indigo-500/10 to-indigo-500/5 border-indigo-500/20 text-indigo-600",
};

export function DraggableAgent({ 
  type, 
  subType,
  label, 
  description, 
  icon: Icon, 
  color, 
  collapsed,
  disabled,
  tooltip,
}: DraggableAgentProps) {
  const onDragStart = (event: React.DragEvent) => {
    if (disabled) {
      event.preventDefault();
      return;
    }
    const data = { type, subType, label };
    event.dataTransfer.setData("application/reactflow", JSON.stringify(data));
    event.dataTransfer.effectAllowed = "move";
  };
  
  return (
    <TooltipProvider>
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>
          <div
            draggable={!disabled}
            onDragStart={onDragStart}
            className={cn(
              "cursor-grab active:cursor-grabbing rounded-2xl p-4 transition-all border group relative overflow-hidden",
              "bg-gradient-to-br backdrop-blur-sm shadow-sm",
              colorClasses[color],
              disabled && "opacity-40 cursor-not-allowed grayscale",
              !disabled && "hover:scale-[1.02] hover:shadow-md hover:border-current/40"
            )}
          >
            <div className="flex items-center gap-4 relative z-10">
              <div className="w-10 h-10 rounded-xl bg-white/50 flex items-center justify-center border border-white/50 shadow-inner group-hover:scale-110 transition-transform">
                <Icon className="h-5 w-5" />
              </div>
              {!collapsed && (
                <div className="flex-1 min-w-0">
                  <h3 className="font-bold text-[11px] uppercase tracking-wider truncate">{label}</h3>
                  <p className="text-[10px] opacity-60 truncate leading-tight mt-0.5">{description}</p>
                </div>
              )}
              {!collapsed && (
                <GripVertical className="h-4 w-4 opacity-20 group-hover:opacity-40 transition-opacity" />
              )}
            </div>
            
            {/* Animated background pulse on hover */}
            {!disabled && (
              <div className="absolute inset-0 bg-white/20 translate-y-full group-hover:translate-y-0 transition-transform duration-500 pointer-events-none" />
            )}
          </div>
        </TooltipTrigger>
        {(disabled || collapsed) && (
          <TooltipContent side="right" className="bg-bee-black text-white border-none rounded-xl p-3 text-xs">
            <p className="font-bold">{label}</p>
            <p className="opacity-60">{tooltip || description}</p>
          </TooltipContent>
        )}
      </Tooltip>
    </TooltipProvider>
  );
}
