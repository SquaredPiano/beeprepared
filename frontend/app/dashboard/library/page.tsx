"use client";

import React, { useEffect, useState } from "react";
import {
  Search,
  Filter,
  MoreVertical,
  FileText,
  Download,
  Trash2,
  Eye,
  Workflow,
  ArrowRight,
  Layout,
  Book,
  FileBadge,
  Presentation,
  History,
  Plus
} from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { supabase } from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

const tabs = [
  { id: "projects", label: "All Projects", icon: Workflow },
  { id: "recent", label: "Recently Visited", icon: History },
];


export default function LibraryPage() {
  const [activeTab, setActiveTab] = useState("projects");
  const [projects, setProjects] = useState<any[]>([]);
  const [artifacts, setArtifacts] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    async function fetchData() {
      try {
        const [projectsData, vaultData, jobsData] = await Promise.all([
          api.projects.list(),
          api.vault.list("/"),
          api.jobs.list()
        ]);

        setProjects(projectsData);
        setArtifacts(vaultData.files || []);
        setJobs(jobsData || []);
      } catch (error: any) {
        console.error("Fetch error:", error);
        toast.error("Failed to load library data");
      } finally {
        setIsLoading(false);
      }
    }

    fetchData();

    // Realtime Subscription (Push-based updates)
    const channel = supabase.channel('active-jobs')
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'jobs' },
        (payload) => {
          console.log('Realtime update:', payload);
          // Refresh jobs list on any change
          api.jobs.list().then((updatedJobs) => {
            setJobs(updatedJobs || []);
            // Check if a job just completed to refresh artifacts
            if (payload.eventType === 'UPDATE' && payload.new.status === 'completed') {
              api.vault.list("/").then(vaultData => setArtifacts(vaultData.files || []));
              toast.success("Job completed!");
            }
          });
        }
      )
      .subscribe();

    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  const activeJobs = jobs.filter(j => ['pending', 'running', 'failed'].includes(j.status));

  const renderContent = () => {
    if (activeTab === "projects") {
      return (
        <motion.div
          key="projects"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -20 }}
          className="space-y-8"
        >
          {/* Active Jobs Section */}
          {activeJobs.length > 0 && (
            <div className="space-y-4 mb-8">
              <h3 className="text-sm font-bold uppercase tracking-widest opacity-60">Active Processes</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {activeJobs.map(job => (
                  <div key={job.id} className={cn(
                    "p-4 rounded-2xl border flex items-center gap-4 bg-white/50 backdrop-blur-sm",
                    job.status === 'failed' ? "border-red-200 bg-red-50/50" : "border-honey/20"
                  )}>
                    <div className={cn(
                      "w-10 h-10 rounded-xl flex items-center justify-center",
                      job.status === 'failed' ? "bg-red-100 text-red-600" : "bg-honey/10 text-honey animate-pulse"
                    )}>
                      {job.status === 'failed' ? <Trash2 size={18} /> : <Workflow size={18} />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <p className="text-xs font-bold uppercase">{job.type} Job</p>
                        <span className={cn(
                          "text-[8px] font-black uppercase tracking-widest px-2 py-0.5 rounded-full",
                          job.status === 'failed' ? "bg-red-200 text-red-700" : "bg-honey text-white"
                        )}>
                          {job.status}
                        </span>
                      </div>
                      <p className="text-[10px] opacity-60 truncate">
                        {job.error_message || `Processing ${job.payload?.original_name || 'task'}...`}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            <button
              onClick={() => router.push("/dashboard/canvas")}
              className="group p-8 rounded-[3rem] border-2 border-dashed border-border/40 hover:border-honey-500 transition-all flex flex-col items-center justify-center gap-6 min-h-[320px] bg-honey-50/5 hover:bg-honey-50/20 cursor-pointer"
            >
              <div className="w-16 h-16 rounded-full bg-white shadow-xl flex items-center justify-center group-hover:scale-110 transition-transform">
                <Plus className="w-8 h-8 text-honey-600" />
              </div>
              <div className="text-center space-y-2">
                <h3 className="text-sm font-bold uppercase tracking-widest">Create New Project</h3>
                <p className="text-[10px] font-medium opacity-40 uppercase tracking-tighter">Start from a blank canvas</p>
              </div>
            </button>


            {isLoading ? (
              Array(2).fill(0).map((_, i) => (
                <div key={i} className="h-80 glass rounded-[3rem] animate-pulse" />
              ))
            ) : projects.map((project, i) => (
              <motion.div
                key={project.id}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.05 }}
                onClick={() => router.push(`/dashboard/canvas?id=${project.id}`)}
                className="group p-10 glass rounded-[3rem] border border-border/40 hover:border-honey-500/50 transition-all cursor-pointer space-y-8 relative overflow-hidden"
              >
                <div className="absolute top-0 right-0 p-8 opacity-0 group-hover:opacity-100 transition-all translate-x-4 group-hover:translate-x-0">
                  <ArrowRight className="w-6 h-6 text-honey-600" />
                </div>

                <div className="w-16 h-16 bg-honey-500 rounded-3xl flex items-center justify-center text-white shadow-2xl shadow-honey-500/40 group-hover:rotate-6 transition-transform duration-500">
                  <Workflow size={32} />
                </div>

                <div className="space-y-3">
                  <h3 className="text-xl font-display font-bold uppercase tracking-tight truncate">{project.name}</h3>
                  <div className="flex items-center gap-4">
                    <span className="px-3 py-1 bg-honey-50 text-honey-700 rounded-full text-[8px] font-bold uppercase tracking-widest">
                      {project.canvas_state?.nodes?.length || 0} Agents
                    </span>

                    <span className="text-[10px] font-bold opacity-30 uppercase tracking-tighter">
                      Updated {new Date(project.updated_at).toLocaleDateString()}
                    </span>
                  </div>
                </div>

                {/* Dynamic activity indicator */}
                <div className="flex items-center gap-2 pt-4">
                  <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
                  <span className="text-[8px] font-bold uppercase tracking-widest opacity-40">Project Saved</span>
                </div>


              </motion.div>
            ))}
          </div>
        </motion.div>
      );
    }

    const filteredArtifacts = artifacts.filter(a => a.type === activeTab || (activeTab === "history" && ["pdf", "audio", "video", "pptx"].includes(a.type)));

    if (filteredArtifacts.length > 0 || (activeTab !== "pipelines" && activeTab !== "history" && ["flashcards", "quizzes", "exams", "pptx"].includes(activeTab))) {
      // If it's one of the main sections, link to the dedicated page
      const sectionRoutes: Record<string, string> = {
        flashcards: "/dashboard/flashcards",
        quizzes: "/dashboard/quizzes",
        exams: "/dashboard/mock-exams",
        pptx: "/dashboard/pptx"
      };

      if (sectionRoutes[activeTab]) {
        return (
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, scale: 0.98 }}
            animate={{ opacity: 1, scale: 1 }}
            className="p-20 glass rounded-[4rem] border-2 border-honey-500/20 bg-honey-50/5 flex flex-col items-center text-center space-y-8"
          >
            <div className="w-24 h-24 rounded-full bg-honey-500 flex items-center justify-center text-white shadow-2xl shadow-honey-500/40">
              {activeTab === "flashcards" && <Layout size={48} />}
              {activeTab === "quizzes" && <Book size={48} />}
              {activeTab === "exams" && <FileBadge size={48} />}
              {activeTab === "pptx" && <Presentation size={48} />}
            </div>
            <div className="space-y-4">
              <h3 className="text-4xl font-display font-bold uppercase tracking-tighter">View {activeTab}</h3>
              <p className="text-xs font-medium opacity-40 max-w-md uppercase tracking-[0.2em] leading-relaxed mx-auto">
                Access your generated study materials and project outputs.
              </p>
            </div>

            <button
              onClick={() => router.push(sectionRoutes[activeTab])}
              className="px-12 py-6 bg-bee-black text-white text-[10px] font-black uppercase tracking-[0.4em] rounded-[2rem] hover:bg-honey-600 transition-all shadow-2xl hover:scale-105 active:scale-95"
            >
              Open View
            </button>

          </motion.div>
        );
      }
    }

    return (
      <motion.div
        key="empty"
        initial={{ opacity: 0, x: 20 }}
        animate={{ opacity: 1, x: 0 }}
        exit={{ opacity: 0, x: -20 }}
        className="flex flex-col items-center justify-center py-24 space-y-8 glass rounded-[4rem] border border-dashed border-border/40"
      >
        <div className="w-24 h-24 rounded-full bg-honey-50 flex items-center justify-center text-honey-200">
          {activeTab === "flashcards" && <Layout size={48} />}
          {activeTab === "quizzes" && <Book size={48} />}
          {activeTab === "exams" && <FileBadge size={48} />}
          {activeTab === "pptx" && <Presentation size={48} />}
          {activeTab === "history" && <History size={48} />}
        </div>
        <div className="text-center space-y-3">
          <h3 className="text-2xl font-display font-bold uppercase tracking-tight">No {activeTab} Generated Yet</h3>
          <p className="text-xs font-medium opacity-40 max-w-sm uppercase tracking-widest leading-relaxed">
            Connect a content node to a process node in the canvas to start generating results.
          </p>
        </div>

        <button
          onClick={() => router.push("/dashboard/canvas")}
          className="px-10 py-5 bg-bee-black text-white text-[10px] font-bold uppercase tracking-[0.3em] rounded-[2rem] hover:bg-honey-600 transition-all shadow-2xl"
        >
          Enter Architecture View
        </button>
      </motion.div>
    );
  };

  return (
    <div className="p-12 space-y-12 max-w-7xl mx-auto">
      <header className="flex items-end justify-between">
        <div className="space-y-4">
          <h1 className="text-6xl font-display uppercase tracking-tighter leading-[0.8]">
            Knowledge <br />
            <span className="italic lowercase opacity-40">Library</span>
          </h1>
          <p className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-40 max-w-xs leading-relaxed">
            Your archived artifacts and synthesized knowledge base.
          </p>
        </div>

        <div className="flex gap-4">
          <div className="glass flex p-1 rounded-2xl border border-border/40 overflow-x-auto scrollbar-none">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "flex items-center gap-3 px-6 py-3 rounded-xl transition-all duration-500 text-[10px] font-bold uppercase tracking-widest shrink-0 cursor-pointer",
                    activeTab === tab.id
                      ? "bg-bee-black text-white shadow-xl"
                      : "text-bee-black/40 hover:text-bee-black hover:bg-honey-50"
                  )}
                >
                  <Icon size={14} />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>
      </header>

      <div className="min-h-[60vh]">
        <AnimatePresence mode="wait">
          {renderContent()}
        </AnimatePresence>
      </div>
    </div>
  );
}
