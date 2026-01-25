"use client";

import React, { useRef, useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  Plus, 
  ArrowUpRight, 
  Clock, 
  LayoutGrid, 
  Settings,
  Search,
  BookOpen,
  FileText,
  Hexagon,
  Trash2,
  ExternalLink,
  MoreVertical,
  Loader2
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";
import { api, Project } from "@/lib/api";
import { generateProjectName } from "@/lib/utils/naming";
import { toast } from "sonner";
import { 
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { useStore } from "@/store/useStore";

export default function DashboardPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [balance, setBalance] = useState(0);
  const container = useRef(null);

  const { getTotalUsedStorage } = useStore();
  const storageUsed = getTotalUsedStorage();
  const storageUsedPercent = Math.min(100, Math.round((storageUsed / (1024**3)) * 100));

  const fetchDashboardData = async () => {
    setIsLoading(true);
    try {
      const [projectsData, balanceData] = await Promise.all([
        api.projects.list(),
        api.points.getBalance()
      ]);
      setProjects(projectsData);
      setBalance(balanceData);
    } catch (error: any) {
      toast.error("Failed to sync with Project server");
    } finally {
      setIsLoading(false);
    }

  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  useGSAP(() => {
    if (!container.current || isLoading) return;
    
    gsap.set(".reveal", { opacity: 0, y: 15 });
    
    const tl = gsap.timeline({ 
      defaults: { ease: "power3.out", duration: 0.8 }
    });
    
    tl.to(".reveal", {
      opacity: 1,
      y: 0,
      stagger: 0.05
    });

    return () => {
      tl.kill();
    };
  }, { scope: container, dependencies: [isLoading] });

  const handleCreateProject = async () => {
    const name = generateProjectName();
    toast.promise(api.projects.create(name), {
      loading: 'Creating new matrix...',
      success: (newProj) => {
        setProjects(prev => [newProj as Project, ...prev]);
        return `Project "${name}" created`;
      },
      error: 'Creation failed'
    });
  };


  const handleDeleteProject = async (id: string) => {
    try {
      await api.projects.delete(id);
      setProjects(prev => prev.filter(p => p.id !== id));
      toast.success("Project deleted");
    } catch (error) {
      toast.error("Failed to delete project");
    }
  };

  const stats = [
    { label: "Projects", value: projects.length.toString(), icon: LayoutGrid },
    { label: "Honey Points", value: balance.toLocaleString(), icon: BookOpen },
    { label: "Capacity", value: `${storageUsedPercent}% used`, icon: Clock },
  ];


  return (
    <div ref={container} className="max-w-6xl mx-auto px-8 md:px-12 py-16 space-y-16 min-h-screen bg-cream/30">
      {/* Hero Section */}
      <header className="flex flex-col md:flex-row justify-between items-end gap-8 border-b border-wax/40 pb-12 reveal">
        <div className="space-y-4 max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-honey/10 text-honey text-[10px] font-bold uppercase tracking-widest border border-honey/20">
            <div className="w-1.5 h-1.5 rounded-full bg-honey animate-pulse" />
            System Online
          </div>
          <h1 className="text-5xl md:text-6xl font-serif italic leading-[0.9] tracking-tighter text-bee-black">
            Dashboard
          </h1>
        </div>
        <div>
          <Button 
            onClick={handleCreateProject}
            className="group flex items-center gap-4 bg-bee-black text-white px-8 py-7 rounded-2xl hover:bg-honey hover:text-bee-black transition-all duration-500 cursor-pointer shadow-xl shadow-bee-black/10 active:scale-95 border-none"
          >
            <span className="text-sm uppercase tracking-widest font-bold">New Project</span>
            <div className="w-10 h-10 bg-white/10 rounded-xl flex items-center justify-center group-hover:rotate-90 transition-transform duration-500">
              <Plus className="w-5 h-5" />
            </div>
          </Button>
        </div>
      </header>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {stats.map((stat, i) => (
          <div
            key={stat.label}
            className="p-8 bg-white/60 backdrop-blur-xl rounded-[2rem] border border-wax/50 space-y-6 group hover:border-honey/30 transition-all duration-500 reveal shadow-sm"
          >
            <div className="flex justify-between items-start">
              <div className="p-3 bg-cream rounded-2xl group-hover:bg-honey/10 group-hover:text-honey transition-colors border border-wax/20">
                <stat.icon className="w-5 h-5" />
              </div>
              <div className="w-2 h-2 rounded-full bg-honey/20 group-hover:bg-honey transition-colors" />
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-widest font-bold opacity-40">{stat.label}</p>
              <p className="text-4xl font-sans font-bold mt-1 tracking-tight truncate text-bee-black">{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
        {/* Project Grid */}
        <section className="lg:col-span-2 space-y-8 min-w-0">
          <div className="flex items-center justify-between border-b border-wax/40 pb-4 reveal">
            <h2 className="text-xs uppercase tracking-[0.2em] font-bold opacity-40">Recent Projects</h2>
            <Link href="/dashboard/library" className="text-[10px] uppercase tracking-widest font-bold hover:text-honey transition-colors cursor-pointer flex items-center gap-2">
              View All <ExternalLink size={10} />
            </Link>
          </div>
          
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
            {isLoading ? (
              <div className="col-span-full py-24 flex flex-col items-center justify-center gap-4 text-bee-black/20">
                <Loader2 className="w-8 h-8 animate-spin" />
                <p className="text-[10px] uppercase tracking-widest font-bold">Synchronizing with Hive...</p>
              </div>
            ) : projects.length > 0 ? (
              projects.map((project) => (
                <motion.div
                  key={project.id}
                  layoutId={project.id}
                  className="group relative bg-white/80 backdrop-blur-xl rounded-[2.5rem] border border-wax/50 hover:border-honey/40 transition-all duration-500 cursor-pointer overflow-hidden reveal shadow-sm hover:shadow-xl hover:shadow-honey/5"
                >
                  <Link href={`/dashboard/canvas?id=${project.id}`} className="block p-8 space-y-6">
                    <div className="flex justify-between items-start">
                      <div className="w-12 h-12 bg-cream rounded-2xl flex items-center justify-center group-hover:bg-honey/10 transition-colors border border-wax/20">
                        <Hexagon className="w-6 h-6 opacity-20 group-hover:text-honey group-hover:opacity-100 transition-all" />
                      </div>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-8 w-8 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity" onClick={(e) => e.preventDefault()}>
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" className="rounded-2xl border-wax">
                          <DropdownMenuItem className="gap-2 text-red-600 focus:text-red-600 focus:bg-red-50 rounded-xl m-1" onClick={(e) => {
                            e.preventDefault();
                            handleDeleteProject(project.id);
                          }}>
                            <Trash2 size={14} /> Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                    <div>
                      <h3 className="font-bold text-xl tracking-tight text-bee-black group-hover:text-honey transition-colors uppercase leading-none mb-2">{project.name}</h3>
                      <p className="text-[10px] text-bee-black/40 font-bold uppercase tracking-widest flex items-center gap-2">
                        Updated {new Date(project.updated_at).toLocaleDateString()}
                      </p>
                    </div>
                  </Link>
                  <div className="absolute bottom-0 left-0 right-0 h-1 bg-honey transform scale-x-0 group-hover:scale-x-100 transition-transform duration-700 origin-left" />
                </motion.div>
              ))
            ) : (
              <div className="col-span-full py-24 text-center bg-white/40 backdrop-blur-md rounded-[3rem] border border-dashed border-wax reveal">
                <div className="w-16 h-16 bg-cream rounded-full flex items-center justify-center mx-auto mb-6">
                  <Search className="w-6 h-6 opacity-20" />
                </div>
                <p className="text-[10px] font-bold opacity-40 uppercase tracking-[0.2em] mb-6">Matrix is currently empty</p>
                <Button 
                  onClick={handleCreateProject}
                  variant="outline"
                  className="rounded-full border-wax hover:bg-honey/10 hover:border-honey/30 gap-2 uppercase text-[10px] font-bold tracking-widest px-6"
                >
                  Start New Project
                </Button>
              </div>
            )}
          </div>
        </section>

        {/* Sidebar Controls */}
        <aside className="space-y-12">
          {/* Points Section */}
          <div className="space-y-6 reveal">
            <h2 className="text-xs uppercase tracking-[0.2em] font-bold opacity-40">Your Progress</h2>
            <div className="p-8 bg-bee-black rounded-[2.5rem] space-y-8 relative overflow-hidden group shadow-2xl shadow-bee-black/20">
              <div className="flex items-center justify-between relative z-10">
                <div className="space-y-1">
                  <p className="text-[10px] uppercase tracking-widest font-bold text-white/40">Total Points</p>
                  <div className="flex items-baseline gap-2 text-white">
                    <span className="text-4xl font-sans font-bold">{balance}</span>
                    <span className="text-honey text-xs font-bold uppercase tracking-widest">pts</span>
                  </div>
                </div>
                <div className="w-16 h-16 bg-honey/10 rounded-3xl flex items-center justify-center border border-honey/20 group-hover:rotate-12 transition-transform duration-500 backdrop-blur-md">
                  <span className="text-3xl filter grayscale group-hover:grayscale-0 transition-all">🍯</span>
                </div>
              </div>

              <div className="space-y-4 relative z-10">
                <div className="flex justify-between text-[10px] uppercase tracking-widest font-bold text-white/60">
                  <span>Level: Starter</span>
                  <span className="text-honey">Next: 1,000</span>
                </div>
                <div className="h-2 bg-white/10 rounded-full overflow-hidden border border-white/5">
                  <motion.div 
                    className="h-full bg-honey"
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.min((balance / 1000) * 100, 100)}%` }}
                    transition={{ duration: 1.5, ease: [0.16, 1, 0.3, 1] }}
                  />
                </div>
              </div>

              <div className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 w-48 h-48 bg-honey/10 rounded-full blur-3xl" />
            </div>
          </div>

          <div className="space-y-6 reveal">
            <h2 className="text-xs uppercase tracking-[0.2em] font-bold opacity-40">Quick Access</h2>
            <div className="space-y-3">
              <Link href="/dashboard/settings" className="w-full flex items-center justify-between p-5 rounded-[1.5rem] bg-white border border-wax/50 hover:border-honey/30 hover:bg-honey/5 transition-all group cursor-pointer shadow-sm">
                <div className="flex items-center gap-4">
                  <div className="p-2 bg-cream rounded-xl group-hover:bg-white transition-colors">
                    <Settings className="w-4 h-4 opacity-40 group-hover:text-honey transition-colors" />
                  </div>
                  <span className="text-[10px] uppercase tracking-[0.2em] font-bold text-bee-black/60">Settings</span>
                </div>
                <div className="w-1.5 h-1.5 rounded-full bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.5)]" />
              </Link>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
