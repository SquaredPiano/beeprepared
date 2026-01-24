"use client";

import React, { useState } from "react";
import { LegalModals } from "./LegalModals";

type ModalTab = "privacy" | "terms" | "docs";

export function Footer() {
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

  const currentYear = new Date().getFullYear();

  return (
    <footer className="relative z-10 py-24 border-t border-bee-black/5 bg-background overflow-hidden">
      {/* Texture and Grid Background */}
      <div className="absolute inset-0 z-[-1] pointer-events-none opacity-[0.6] bg-[url('https://grainy-gradients.vercel.app/noise.svg')] brightness-100 contrast-150 mix-blend-multiply" />
      <div className="absolute inset-0 z-[-2] pointer-events-none opacity-[0.05] bg-[linear-gradient(to_right,#808080_1px,transparent_1px),linear-gradient(to_bottom,#808080_1px,transparent_1px)] bg-[size:4rem_4rem]" />
      
      {/* Honey Accents */}
      <div className="absolute top-0 left-1/4 w-96 h-96 bg-honey-400/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-0 right-1/4 w-64 h-64 bg-honey-600/5 blur-[100px] rounded-full pointer-events-none" />

      <div className="container mx-auto px-6">
        <div className="flex flex-col md:flex-row justify-between items-center gap-8">
          <div className="flex flex-col items-center md:items-start gap-2">
            <h3 className="font-display uppercase tracking-widest text-sm font-bold text-bee-black">
              BeePrepared
            </h3>
            <p className="text-[10px] uppercase tracking-[0.2em] text-bee-black/30">
              © {currentYear} Cognitive Hive Architecture
            </p>
          </div>

          <div className="flex items-center gap-8">
            <button
              onClick={() => openModal("docs")}
              className="text-[10px] uppercase tracking-[0.2em] font-bold text-bee-black/40 hover:text-honey-600 transition-colors"
            >
              Documentation
            </button>
            <button
              onClick={() => openModal("privacy")}
              className="text-[10px] uppercase tracking-[0.2em] font-bold text-bee-black/40 hover:text-honey-600 transition-colors"
            >
              Privacy
            </button>
            <button
              onClick={() => openModal("terms")}
              className="text-[10px] uppercase tracking-[0.2em] font-bold text-bee-black/40 hover:text-honey-600 transition-colors"
            >
              Terms
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
