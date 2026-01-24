"use client";

import React, { useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { useTaskPolling } from "@/hooks/useTaskPolling";
import { FlowCanvas } from "@/components/canvas/FlowCanvas";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { 
  ArrowRight, 
  Clock, 
  Workflow,
  Sparkles,
  Search,
  Archive
} from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";

export default function ProcessingPage() {
  const params = useParams();
  const router = useRouter();
  const taskId = params.taskId as string;
  const { data, isLoading, error } = useTaskPolling(taskId);
  const containerRef = useRef(null);

  useGSAP(() => {
    gsap.from(".reveal", {
      y: 30,
      opacity: 0,
      duration: 1,
      stagger: 0.1,
      ease: "power3.out"
    });
  }, { scope: containerRef });

  if (isLoading) {
    return (
      <div className="min-h-[80vh] flex flex-col items-center justify-center">
        <div className="w-12 h-12 bg-honey-500 rounded-full animate-ping mb-8" />
        <p className="text-sm font-display uppercase tracking-widest font-bold opacity-40">Initialising Flow</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-[80vh] flex flex-col items-center justify-center p-6 text-center">
        <div className="w-16 h-16 bg-red-50 text-red-500 rounded-2xl flex items-center justify-center mb-8">
          <Workflow className="w-8 h-8" />
        </div>
        <h1 className="text-2xl font-display uppercase tracking-tight mb-4">Flow Interrupted</h1>
        <p className="text-muted-foreground mb-12 max-w-md">The processing encountered an unexpected state. Please try again.</p>
        <Link href="/upload" className="bg-bee-black text-white px-8 py-4 rounded-full font-display text-sm uppercase tracking-widest font-bold hover:bg-honey-500 transition-all cursor-pointer">
          Try Again
        </Link>
      </div>
    );
  }

  const status = data?.status || "queued";
  const progress = data?.progress || 0;
  const stage = data?.stage || "Preparing";

  return (
    <div ref={containerRef} className="container mx-auto px-6 py-20 min-h-screen">
      <div className="max-w-6xl mx-auto space-y-20">
        {/* Header */}
        <div className="space-y-6 max-w-2xl">
          <div className="reveal flex items-center gap-3">
            <div className="h-px w-8 bg-border/60" />
            <span className="text-[10px] font-bold uppercase tracking-widest opacity-40">Task ID: {taskId.slice(0, 8)}</span>
          </div>
          
          <h1 className="reveal text-5xl md:text-7xl font-display uppercase leading-none tracking-tighter">
            Processing <br />
            <span className="font-serif italic lowercase opacity-40">Content</span>
          </h1>
          
          <p className="reveal text-lg text-muted-foreground font-medium uppercase tracking-tight max-w-md opacity-60">
            Analyzing your file. We're building your study materials and organizing them for your library.
          </p>
        </div>

        {/* Canvas & Progress */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-12 items-start">
          <div className="lg:col-span-8 reveal">
            <div className="h-[500px]">
              <FlowCanvas currentStage={stage} progress={progress} />
            </div>
          </div>

          <div className="lg:col-span-4 space-y-8 reveal">
            <div className="p-8 rounded-3xl border border-border/40 bg-white/50 backdrop-blur-md space-y-10">
              <div className="space-y-4">
                <div className="flex justify-between items-end">
                  <div className="space-y-1">
                    <p className="text-[10px] font-bold uppercase tracking-widest opacity-40">Stage</p>
                    <p className="text-xl font-display uppercase tracking-tight">{stage}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-3xl font-display font-bold text-honey-600 leading-none">{progress}%</p>
                  </div>
                </div>
                <Progress value={progress} className="h-1.5 bg-honey-100" />
              </div>

              <div className="space-y-6">
                  <div className="flex items-center gap-4 p-5 rounded-2xl bg-stone-50/50 border border-border/20">
                    <div className="w-10 h-10 bg-white rounded-xl flex items-center justify-center shadow-sm">
                      <Clock className="w-5 h-5 text-honey-600" />
                    </div>
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-widest opacity-40 leading-none mb-1">Time Remaining</p>
                      <p className="text-sm font-bold uppercase tracking-tight">~{data?.eta_seconds || "Calculating"}s</p>
                    </div>
                  </div>
                </div>
              </div>

            {status === "complete" && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.8, ease: "circOut" }}
              >
                <Link 
                  href={`/artifacts/${data.artifact_id}`}
                  className="group flex items-center justify-between w-full bg-bee-black text-white p-6 rounded-full hover:bg-honey-500 transition-all duration-500 shadow-2xl cursor-pointer"
                >
                  <span className="font-display text-sm uppercase tracking-widest font-bold ml-4">Access Library</span>
                  <div className="w-12 h-12 bg-white/10 rounded-full flex items-center justify-center group-hover:bg-white/20 transition-all">
                    <ArrowRight className="w-6 h-6 text-white" />
                  </div>
                </Link>
              </motion.div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
