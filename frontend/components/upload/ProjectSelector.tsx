"use client";

import React, { useEffect, useState } from "react";
import { api, Project } from "@/lib/api";
import { Check, ChevronDown, Hexagon, Plus, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";

interface ProjectSelectorProps {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export function ProjectSelector({ selectedId, onSelect }: ProjectSelectorProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function fetchProjects() {
      try {
        const data = await api.projects.list();
        setProjects(data);
        // Default to most recent if none selected
        if (!selectedId && data.length > 0) {
          onSelect(data[0].id);
        }
      } catch (error) {
        console.error("Failed to fetch projects:", error);
      } finally {
        setIsLoading(false);
      }
    }
    fetchProjects();
  }, [selectedId, onSelect]);

  const selectedProject = projects.find(p => p.id === selectedId);

  return (
    <div className="relative w-full max-w-md">
      <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-bee-black/30 mb-3 ml-4">Target Hive</p>
      
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-6 py-4 bg-white border border-wax rounded-2xl hover:border-honey-500/50 transition-all shadow-sm group cursor-pointer"
      >
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-honey/10 flex items-center justify-center border border-honey/20">
            <Hexagon size={18} className="text-honey-600 fill-honey-600/20" />
          </div>
          <div className="text-left">
            <h3 className="font-bold text-bee-black truncate max-w-[200px]">
              {selectedProject?.name || "Select Project"}
            </h3>
            <p className="text-[9px] uppercase tracking-widest font-bold opacity-30">
              {selectedProject ? `ID: ${selectedProject.id.slice(0, 8)}` : "Choose where to store assets"}
            </p>
          </div>
        </div>
        <ChevronDown size={16} className={cn("text-bee-black/20 transition-transform duration-300", isOpen && "rotate-180")} />
      </button>

      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setIsOpen(false)}
              className="fixed inset-0 z-[60]"
            />
            <motion.div
              initial={{ opacity: 0, y: 10, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.95 }}
              className="absolute top-full left-0 right-0 mt-3 p-2 bg-white border border-wax rounded-[2rem] shadow-2xl z-[70] max-h-[400px] overflow-hidden flex flex-col"
            >
              <div className="p-4 border-b border-wax">
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3 h-3 text-bee-black/20" />
                  <input 
                    placeholder="Search projects..."
                    className="w-full pl-9 pr-4 py-2 bg-wax/20 rounded-xl text-xs font-medium focus:outline-none"
                  />
                </div>
              </div>
              
              <div className="overflow-y-auto p-2 space-y-1">
                {projects.map((project) => (
                  <button
                    key={project.id}
                    onClick={() => {
                      onSelect(project.id);
                      setIsOpen(false);
                    }}
                    className={cn(
                      "w-full flex items-center justify-between p-3 rounded-xl transition-all cursor-pointer group",
                      selectedId === project.id ? "bg-honey/10" : "hover:bg-cream"
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div className={cn(
                        "w-8 h-8 rounded-lg flex items-center justify-center transition-colors",
                        selectedId === project.id ? "bg-honey text-white" : "bg-wax/20 text-bee-black/20 group-hover:bg-honey/20 group-hover:text-honey"
                      )}>
                        <Hexagon size={14} />
                      </div>
                      <span className="text-xs font-bold text-bee-black uppercase tracking-tight">{project.name}</span>
                    </div>
                    {selectedId === project.id && <Check size={14} className="text-honey" />}
                  </button>
                ))}
              </div>
              
              <button 
                className="p-4 bg-cream flex items-center justify-center gap-2 text-[9px] font-bold uppercase tracking-widest text-honey-600 hover:bg-honey-50 transition-colors"
                onClick={() => {
                  window.location.href = "/dashboard/canvas";
                }}
              >
                <Plus size={12} /> Create New Project
              </button>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
