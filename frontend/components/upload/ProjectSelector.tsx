"use client";

import React, { useEffect, useState } from "react";
import { api, Project } from "@/lib/api";
import { Check, ChevronDown, Hexagon, Loader2, Plus, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";

interface ProjectSelectorProps {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

export function ProjectSelector({ selectedId, onSelect }: ProjectSelectorProps) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");



  useEffect(() => {
    async function fetchProjects() {
      try {
        const data = await api.projects.list();
        setProjects(data);
        
        // If we have a selectedId that is NOT in the new list, or if we have no selectedId
        // but we DO have projects, auto-select the first one.
        if (data.length > 0) {
          const currentExists = data.find(p => p.id === selectedId);
          if (!selectedId || !currentExists) {
            onSelect(data[0].id);
          }
        }
      } catch (error) {
        console.error("Failed to fetch projects:", error);
      } finally {
        setIsLoading(false);
      }
    }
    fetchProjects();
  }, [selectedId, onSelect]);

  const handleCreateInline = async () => {
    if (!newProjectName.trim() || isLoading) return;
    
    setIsLoading(true);
    try {
      const newProj = await api.projects.create(newProjectName.trim());
      setProjects(prev => [newProj, ...prev]);
      onSelect(newProj.id);
      setIsCreating(false);
      setNewProjectName("");
      toast.success("Project created");
    } catch (err) {
      console.error("Failed to create project:", err);
      toast.error("Failed to create project");
    } finally {
      setIsLoading(false);
    }
  };

  const selectedProject = projects.find(p => p.id === selectedId);

  return (
    <div className="relative w-full max-w-md">
      <p className="text-[10px] font-bold uppercase tracking-[0.3em] text-bee-black/30 mb-3 ml-4">Target Project</p>
      
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
              {selectedProject ? `ID: ${selectedProject.id.slice(0, 8)}` : "Choose where to store files"}
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
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="w-full pl-9 pr-4 py-2 bg-wax/20 rounded-xl text-xs font-medium focus:outline-none"
                  />
                </div>
              </div>

              
              <div className="overflow-y-auto p-2 space-y-1">
                {projects.filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase())).length > 0 ? (
                  projects.filter(p => !search || p.name.toLowerCase().includes(search.toLowerCase())).map((project) => (
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
                  ))
                ) : (
                  <div className="p-12 text-center space-y-4">
                    <div className="w-16 h-16 bg-cream rounded-full flex items-center justify-center mx-auto opacity-20">
                      <Hexagon size={32} />
                    </div>
                    <div className="space-y-1">
                      <p className="text-[10px] font-bold uppercase tracking-[0.2em] opacity-40">No Projects Found</p>
                      <p className="text-[8px] uppercase tracking-widest opacity-20">Create or sync your first matrix</p>
                    </div>
                    <Button 
                      onClick={() => setIsCreating(true)}
                      variant="outline"
                      className="rounded-full border-wax hover:bg-honey/10 transition-all text-[9px] font-bold uppercase tracking-widest px-6"
                    >
                      Create First Project
                    </Button>
                  </div>
                )}
              </div>

              
              <div className="p-4 bg-white border-t border-wax shadow-[0_-4px_12px_rgba(0,0,0,0.02)]">
                {isCreating ? (
                  <div className="flex items-center gap-2">
                    <div className="relative flex-1">
                      <input
                        autoFocus
                        placeholder="New Project Name..."
                        value={newProjectName}
                        onChange={(e) => setNewProjectName(e.target.value)}
                        disabled={isLoading}
                        onKeyDown={async (e) => {
                          if (e.key === 'Enter' && newProjectName.trim() && !isLoading) {
                            handleCreateInline();
                          } else if (e.key === 'Escape') {
                            setIsCreating(false);
                          }
                        }}
                        className="w-full px-4 py-2.5 bg-cream/30 border-2 border-wax rounded-xl text-xs font-bold text-bee-black focus:outline-none focus:border-honey transition-all placeholder:text-bee-black/20"
                      />
                    </div>
                    
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCreateInline();
                      }}
                      disabled={!newProjectName.trim() || isLoading}
                      title="Create Project"
                      className="p-2.5 bg-[#fbbf24] text-white rounded-xl hover:bg-bee-black transition-all shadow-lg shadow-honey/40 disabled:opacity-50 disabled:shadow-none flex items-center justify-center min-w-[40px] border border-[#f59e0b]/50"
                    >
                      {isLoading ? <Loader2 size={16} className="animate-spin" /> : <Check size={18} strokeWidth={4} />}
                    </button>

                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        setIsCreating(false);
                      }}
                      disabled={isLoading}
                      className="p-2.5 bg-wax/10 text-bee-black/40 hover:bg-wax/20 hover:text-bee-black rounded-xl transition-all"
                    >
                      <X size={16} />
                    </button>
                  </div>
                ) : (
                  <button 
                    className="w-full h-12 flex items-center justify-center gap-3 text-[10px] font-bold uppercase tracking-widest text-honey border-2 border-dashed border-honey/20 hover:border-honey hover:bg-honey/5 rounded-2xl transition-all"
                    onClick={() => setIsCreating(true)}
                  >
                    <Plus size={14} /> Create Blank Matrix
                  </button>
                )}
              </div>



            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
