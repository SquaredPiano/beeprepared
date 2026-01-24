"use client";

import React, { useEffect, useState } from "react";
import { Search, Filter, MoreVertical, FileText, Download, Trash2, Eye, Workflow, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";
import { supabase } from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

const artifacts = [
  { id: "1", name: "Lecture_Notes_Architectural_History.pdf", type: "PDF", size: "2.4 MB", date: "Jan 22, 2026", status: "completed" },
  { id: "2", name: "Deep_Learning_Synthesis.mp3", type: "Audio", size: "15.8 MB", date: "Jan 21, 2026", status: "completed" },
  { id: "3", name: "Organic_Chemistry_Matrix.pdf", type: "PDF", size: "1.1 MB", date: "Jan 20, 2026", status: "processing" },
];

export default function LibraryPage() {
  const [projects, setProjects] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    async function fetchProjects() {
      try {
        const { data, error } = await supabase
          .from("projects")
          .select("*")
          .order("updated_at", { ascending: false });

        if (error) throw error;
        setProjects(data || []);
      } catch (error: any) {
        toast.error("Failed to load projects");
      } finally {
        setIsLoading(false);
      }
    }

    fetchProjects();
  }, []);

  return (
    <div className="p-12 space-y-12">
      <header className="space-y-4">
        <h1 className="text-5xl font-display uppercase tracking-tighter">Knowledge <br /> <span className="italic lowercase opacity-40">Library</span></h1>
        <p className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-40 max-w-xs leading-relaxed">
          Your archived artifacts and synthesized knowledge base.
        </p>
      </header>

      {/* Projects Section */}
      <section className="space-y-6">
        <div className="flex items-center justify-between border-b border-border/40 pb-4">
          <h2 className="text-xs font-bold uppercase tracking-[0.3em] opacity-40">Saved Pipelines</h2>
          <span className="text-[10px] font-bold opacity-20 uppercase tracking-widest">{projects.length} Total</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {isLoading ? (
            Array(3).fill(0).map((_, i) => (
              <div key={i} className="h-48 glass rounded-3xl animate-pulse" />
            ))
          ) : projects.length === 0 ? (
            <div className="col-span-full h-48 glass rounded-3xl border border-dashed border-border/40 flex flex-col items-center justify-center space-y-4">
              <p className="text-[10px] font-bold uppercase tracking-widest opacity-20">No saved pipelines found</p>
              <button 
                onClick={() => router.push("/dashboard/canvas")}
                className="text-[10px] font-bold uppercase tracking-widest text-honey-600 hover:text-honey-500 transition-colors cursor-pointer"
              >
                Create your first pipeline →
              </button>
            </div>
          ) : (
            projects.map((project, i) => (
              <motion.div
                key={project.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.05 }}
                onClick={() => router.push(`/dashboard/canvas?id=${project.id}`)}
                className="group p-8 glass rounded-[2.5rem] border border-border/40 hover:border-honey-500/50 transition-all cursor-pointer space-y-6 relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-6 opacity-0 group-hover:opacity-100 transition-opacity">
                  <ArrowRight className="w-5 h-5 text-honey-600" />
                </div>
                
                <div className="w-12 h-12 bg-honey-500 rounded-2xl flex items-center justify-center text-white shadow-lg">
                  <Workflow size={24} />
                </div>

                <div className="space-y-1">
                  <h3 className="text-sm font-bold uppercase tracking-widest truncate">{project.name}</h3>
                  <p className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">
                    {project.nodes?.length || 0} Agents • Updated {new Date(project.updated_at).toLocaleDateString()}
                  </p>
                </div>
              </motion.div>
            ))
          )}
        </div>
      </section>

      {/* Artifacts Section */}
      <section className="space-y-6">
        <div className="flex items-center justify-between border-b border-border/40 pb-4">
          <h2 className="text-xs font-bold uppercase tracking-[0.3em] opacity-40">Knowledge Artifacts</h2>
          <div className="flex gap-4">
            <Search className="w-4 h-4 opacity-20" />
            <Filter className="w-4 h-4 opacity-20" />
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4">
            {artifacts.map((artifact, i) => (
              <motion.div
                key={artifact.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.05 }}
                className="group flex items-center justify-between p-6 glass rounded-3xl border border-border/40 hover:border-honey-300 transition-all cursor-pointer"
              >
              <div className="flex items-center gap-8">
                <div className="w-14 h-14 bg-muted rounded-2xl flex items-center justify-center group-hover:bg-honey-100 group-hover:text-honey-600 transition-colors">
                  <FileText className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-lg font-display font-bold uppercase tracking-tight">{artifact.name}</h3>
                  <div className="flex items-center gap-4 mt-1 opacity-40 text-[10px] font-bold uppercase tracking-[0.2em]">
                    <span>{artifact.type}</span>
                    <div className="w-1 h-1 rounded-full bg-border" />
                    <span>{artifact.size}</span>
                    <div className="w-1 h-1 rounded-full bg-border" />
                    <span>{artifact.date}</span>
                  </div>
                </div>
              </div>
              
              <div className="flex items-center gap-4">
                <div className="flex opacity-0 group-hover:opacity-100 transition-opacity gap-2">
                  <button className="p-3 hover:bg-muted rounded-xl transition-colors"><Eye className="w-4 h-4" /></button>
                  <button className="p-3 hover:bg-muted rounded-xl transition-colors"><Download className="w-4 h-4" /></button>
                  <button className="p-3 hover:bg-red-50 hover:text-red-600 rounded-xl transition-colors"><Trash2 className="w-4 h-4" /></button>
                </div>
                <button className="p-3 opacity-20 group-hover:opacity-100 transition-opacity"><MoreVertical className="w-5 h-5" /></button>
              </div>
            </motion.div>
          ))}
        </div>
      </section>
    </div>
  );
}
