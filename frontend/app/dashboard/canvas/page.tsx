"use client";

import { BeeCanvas } from "@/components/canvas/BeeCanvas";
import { ArrowLeft, Edit3, Check, Hexagon } from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";
import { useSearchParams } from "next/navigation";
import { useEffect, useState, Suspense } from "react";

export default function CanvasPage() {
  return (
    <Suspense fallback={
      <div className="flex h-screen items-center justify-center bg-cream">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-honey border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-bee-black/50 font-bold uppercase tracking-widest text-xs">Entering Matrix...</p>
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

