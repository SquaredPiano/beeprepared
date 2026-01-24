"use client";

import React, { useRef } from "react";
import { useStore } from "@/store/useStore";
import { 
  Plus, 
  ArrowUpRight, 
  Clock, 
  LayoutGrid, 
  Settings,
  Search,
  BookOpen,
  FileText
} from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

const stats = [
  { label: "Files Processed", value: "124", icon: FileText },
  { label: "Hours Saved", value: "42.5", icon: Clock },
  { label: "Insights Found", value: "2.4k", icon: BookOpen },
];

export default function DashboardPage() {
  const { files } = useStore();
  const container = useRef(null);

  useGSAP(() => {
    const tl = gsap.timeline({ defaults: { ease: "power4.out", duration: 1.2 } });
    
    tl.to(".reveal", {
      opacity: 1,
      y: 0,
      stagger: 0.1,
      delay: 0.2
    });
  }, { scope: container });

  return (
    <div ref={container} className="max-w-7xl mx-auto px-6 py-12 space-y-16">
      {/* Hero Section */}
      <header className="flex flex-col md:flex-row justify-between items-end gap-8 border-b border-border/40 pb-12 reveal">
        <div className="space-y-4 max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-honey-50 text-honey-700 text-[10px] font-bold uppercase tracking-widest">
            <div className="w-1.5 h-1.5 rounded-full bg-honey-500 animate-pulse" />
            System Status: Active
          </div>
          <h1 className="text-5xl md:text-6xl font-display leading-[0.9] uppercase tracking-tighter">
            Architectural <br />
            <span className="font-serif italic lowercase opacity-60 pr-4 tracking-normal text-honey-600">Overview</span>
          </h1>
        </div>
        <div>
          <Link 
            href="/upload" 
            className="group flex items-center gap-4 bg-bee-black text-white px-8 py-4 rounded-full hover:bg-honey-500 transition-all duration-500 cursor-pointer"
          >
            <span className="font-display text-sm uppercase tracking-widest font-bold">New Task</span>
            <div className="w-10 h-10 bg-white/10 rounded-full flex items-center justify-center group-hover:rotate-45 transition-transform duration-500">
              <Plus className="w-5 h-5 text-white" />
            </div>
          </Link>
        </div>
      </header>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {stats.map((stat, i) => (
          <div
            key={stat.label}
            className="p-8 glass rounded-2xl border border-border/40 space-y-6 group hover:border-honey-300 transition-colors reveal"
          >
            <div className="flex justify-between items-start">
              <div className="p-3 bg-muted rounded-xl group-hover:bg-honey-100 group-hover:text-honey-600 transition-colors">
                <stat.icon className="w-5 h-5" />
              </div>
              <ArrowUpRight className="w-4 h-4 opacity-20 group-hover:opacity-100 transition-opacity" />
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-widest font-bold opacity-40">{stat.label}</p>
              <p className="text-4xl font-display font-bold mt-1 tracking-tight">{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
        {/* Recent Activity */}
        <section className="lg:col-span-2 space-y-8">
          <div className="flex items-center justify-between border-b border-border/40 pb-4 reveal">
            <h2 className="font-display text-xs uppercase tracking-[0.2em] font-bold opacity-40">Matrix Activity</h2>
            <button className="text-[10px] uppercase tracking-widest font-bold hover:text-honey-600 transition-colors cursor-pointer">View Library</button>
          </div>
          
          <div className="space-y-4">
            {files.length > 0 ? (
              files.map((file, i) => (
                <div
                  key={file.id}
                  className="group flex items-center justify-between p-6 glass rounded-2xl border border-border/40 hover:border-honey-300 transition-all cursor-pointer reveal"
                >
                  <div className="flex items-center gap-6">
                    <div className="w-12 h-12 bg-muted rounded-xl flex items-center justify-center group-hover:bg-honey-50 transition-colors">
                      <FileText className="w-6 h-6 opacity-40 group-hover:text-honey-600 transition-colors" />
                    </div>
                    <div>
                      <h3 className="font-medium text-lg tracking-tight uppercase">{file.name}</h3>
                      <div className="flex items-center gap-3 mt-1 opacity-40 text-[10px] uppercase tracking-widest font-bold">
                        <span>Updated 2h ago</span>
                        <div className="w-1 h-1 rounded-full bg-border" />
                        <span>PDF</span>
                      </div>
                    </div>
                  </div>
                  <div className={cn(
                    "px-4 py-1.5 rounded-full text-[10px] font-bold uppercase tracking-widest border transition-all duration-500",
                    file.status === "completed" 
                      ? "bg-green-50 text-green-700 border-green-100" 
                      : "bg-honey-50 text-honey-700 border-honey-100"
                  )}>
                    {file.status}
                  </div>
                </div>
              ))
            ) : (
              <div className="py-24 text-center glass rounded-2xl border border-dashed border-border/60 reveal">
                <Search className="w-8 h-8 mx-auto opacity-20 mb-4" />
                <p className="text-sm font-medium opacity-40 uppercase tracking-widest">No active artifacts</p>
              </div>
            )}
          </div>
        </section>

        {/* Sidebar Controls */}
        <aside className="space-y-12">
          <div className="space-y-6 reveal">
            <h2 className="font-display text-xs uppercase tracking-[0.2em] font-bold opacity-40">System Node</h2>
            <div className="space-y-3">
              <Link href="/dashboard/canvas" className="w-full flex items-center justify-between p-4 rounded-xl border border-border/40 hover:bg-white transition-all group cursor-pointer">
                <div className="flex items-center gap-3">
                  <LayoutGrid className="w-4 h-4 opacity-40 group-hover:text-honey-500 transition-colors" />
                  <span className="text-xs uppercase tracking-widest font-bold">Flow Matrix</span>
                </div>
                <ArrowUpRight className="w-3 h-3 opacity-20 group-hover:opacity-100 transition-opacity" />
              </Link>
              <Link href="/dashboard/settings" className="w-full flex items-center justify-between p-4 rounded-xl border border-border/40 hover:bg-white transition-all group cursor-pointer">
                <div className="flex items-center gap-3">
                  <Settings className="w-4 h-4 opacity-40 group-hover:text-honey-500 transition-colors" />
                  <span className="text-xs uppercase tracking-widest font-bold">Preferences</span>
                </div>
                <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
              </Link>
            </div>
          </div>

          <div className="p-8 bg-gradient-to-br from-honey-500/10 to-amber-500/10 border border-honey-500/20 rounded-[2.5rem] space-y-6 relative overflow-hidden group reveal">
            <div className="relative z-10 space-y-3">
              <div className="flex items-center gap-2">
                <span className="text-2xl">🎓</span>
                <h3 className="text-xl font-display uppercase leading-none">Free During <span className="text-honey-600 italic">Beta</span></h3>
              </div>
              <p className="text-[10px] uppercase tracking-[0.2em] opacity-60 font-bold leading-relaxed">
                Unlimited processing • Unlimited storage • All features included.
              </p>
              <div className="pt-2 flex flex-col gap-2">
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-bold text-honey-600">
                  <span className="w-1 h-1 rounded-full bg-honey-500" />
                  Built for students
                </div>
                <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-bold text-honey-600">
                  <span className="w-1 h-1 rounded-full bg-honey-500" />
                  Always free for early adopters
                </div>
              </div>
            </div>
            <div className="absolute top-0 right-0 -translate-y-1/2 translate-x-1/2 w-48 h-48 bg-honey-500/10 rounded-full blur-3xl" />
          </div>
        </aside>
      </div>
    </div>
  );
}
