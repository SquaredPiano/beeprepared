"use client";

import { BeeCanvas } from "@/components/canvas/BeeCanvas";
import { motion } from "framer-motion";
import { useSearchParams, useRouter } from "next/navigation";
import { useEffect, Suspense, useRef } from "react";
import { api } from "@/lib/api";
import { generateProjectName } from "@/lib/utils/naming";

export default function CanvasPage() {
  const searchParams = useSearchParams();
  const projectId = searchParams.get("id");
  const router = useRouter();
  const initRef = useRef(false);

  // If no projectId, we are in "resolving" mode (loading/creating)
  const isResolving = !projectId;

  // Auto-redirect to latest project or create new one if no ID
  useEffect(() => {
    if (!isResolving) return;
    if (initRef.current) return;
    initRef.current = true;

    async function resolveProject() {
      try {
        const projects = await api.projects.list();

        if (projects.length > 0) {
          // Sort by updated_at desc just to be safe
          const sorted = projects.sort((a, b) =>
            new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
          );
          router.replace(`/dashboard/canvas?id=${sorted[0].id}`);
        } else {
          // Create new project
          const name = generateProjectName();
          const newProject = await api.projects.create(name);
          router.replace(`/dashboard/canvas?id=${newProject.id}`);
        }
      } catch (error) {
        console.error("Failed to resolve project:", error);
        // Fallback: stay on empty canvas or show error?
        // For now, let's just allow rendering BeeCanvas (empty) via derived state override?
        // Actually, if we fail to resolve, we are stuck in 'isResolving' state (loading).
        // Let's redirect to a default anyway to break the loop or allow empty param.
        // router.replace(`/dashboard/canvas?id=new`); // logic loop risk.
      }
    }

    resolveProject();
  }, [isResolving, router]);

  if (isResolving) {
    return (
      <div className="flex h-screen items-center justify-center bg-cream">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-honey border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-bee-black/50 font-bold uppercase tracking-widest text-xs">Loading Workspace...</p>
        </div>
      </div>
    );
  }

  return (
    <Suspense fallback={
      <div className="flex h-screen items-center justify-center bg-cream">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-honey border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-bee-black/50 font-bold uppercase tracking-widest text-xs">Loading Editor...</p>
        </div>
      </div>

    }>
      <div className="flex flex-col h-screen bg-cream overflow-hidden font-sans">
        <main className="flex-1 relative min-h-0">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, ease: "easeOut" }}
            className="w-full h-full"
          >
            <BeeCanvas />
          </motion.div>
        </main>
      </div>
    </Suspense>
  );
}

