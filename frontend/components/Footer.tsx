"use client";

import React, { useState } from "react";
import { LegalModals } from "./LegalModals";
import { Hexagon } from "lucide-react";

type ModalTab = "privacy" | "terms" | "docs";

interface FooterProps {
  variant?: "light" | "dark";
}

export function Footer({ variant = "light" }: FooterProps) {
  const [modalState, setModalState] = useState<{
    isOpen: boolean;
    tab: ModalTab;
  }>({
    isOpen: false,
    tab: "privacy",
  });

  const openModal = (tab: ModalTab) => {
    setModalState({ isOpen: true, tab });
  };

  const closeModal = () => {
    setModalState((prev) => ({ ...prev, isOpen: false }));
  };

  const isDark = variant === "dark";

  return (
    <footer className={`relative z-10 px-8 md:px-16 lg:px-24 py-16 md:py-20 border-t-4 ${
      isDark 
        ? "bg-bee-black text-white border-white/5" 
        : "bg-bee-black text-white border-white/5"
    }`}>
      <div className="flex flex-col md:flex-row justify-between items-start md:items-end gap-12">
        <div className="space-y-6">
          <div className="flex items-center gap-3">
            <Hexagon size={36} className="text-honey fill-honey" />
            <span className="font-black uppercase tracking-tighter text-2xl md:text-3xl">BeePrepared</span>
          </div>
          <div className="max-w-xs text-honey/40 font-bold uppercase tracking-widest text-[9px] leading-relaxed cursor-text">
            Design for Mastery. Engineered for High-Fidelity Knowledge Synthesis. 
            The Intentional Workspace for Students.
          </div>
          <p className="text-honey/20 font-bold uppercase tracking-widest text-[8px]">
            Knowledge Architecture © 2026
          </p>
        </div>
        
        <div className="flex flex-col items-start md:items-end gap-8">
          <div className="flex flex-wrap gap-6">
            <button 
              onClick={() => openModal("privacy")} 
              className="text-[9px] font-black uppercase tracking-[0.15em] hover:text-honey transition-colors cursor-pointer"
            >
              Privacy
            </button>
            <button 
              onClick={() => openModal("terms")} 
              className="text-[9px] font-black uppercase tracking-[0.15em] hover:text-honey transition-colors cursor-pointer"
            >
              Terms
            </button>
            <button 
              onClick={() => openModal("docs")} 
              className="text-[9px] font-black uppercase tracking-[0.15em] hover:text-honey transition-colors cursor-pointer"
            >
              Support
            </button>
          </div>
        </div>
      </div>

      <LegalModals
        isOpen={modalState.isOpen}
        onClose={closeModal}
        initialTab={modalState.tab}
      />
    </footer>
  );
}
