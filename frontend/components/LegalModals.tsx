"use client";

import React, { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";

type ModalTab = "privacy" | "terms" | "docs";

interface LegalModalsProps {
  isOpen: boolean;
  onClose: () => void;
  initialTab?: ModalTab;
}

export function LegalModals({ isOpen, onClose, initialTab = "privacy" }: LegalModalsProps) {
  const [activeTab, setActiveTab] = useState<ModalTab>(initialTab);

  useEffect(() => {
    if (isOpen) {
      setActiveTab(initialTab);
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "unset";
    }
    return () => {
      document.body.style.overflow = "unset";
    };
  }, [isOpen, initialTab]);

  const tabs: { id: ModalTab; label: string }[] = [
    { id: "docs", label: "Documentation" },
    { id: "privacy", label: "Privacy" },
    { id: "terms", label: "Terms" },
  ];

  const content = {
    docs: {
      title: "Hive Documentation",
      body: (
        <div className="space-y-6 text-bee-black/80">
          <section>
            <h4 className="font-display uppercase text-xs tracking-widest text-honey-600 mb-2">Cognitive Architecture</h4>
            <p>BeePrepared operates on a multi-stage hexagonal pipeline. Each document is ingested, fragmented into atomic knowledge units, and then re-synthesized by our neural foragers into high-fidelity artifacts.</p>
          </section>
          <section>
            <h4 className="font-display uppercase text-xs tracking-widest text-honey-600 mb-2">Ingestion Protocol</h4>
            <p>Supported artifacts: PDF (text-layer and OCR), MP3, WAV, and MP4. Maximum artifact weight: 50MB per unit.</p>
          </section>
          <section>
            <h4 className="font-display uppercase text-xs tracking-widest text-honey-600 mb-2">Artifact Generation</h4>
            <p>The hive generates four primary artifact types: Synoptic Overviews, Recursive Q&A, Structural Outlines, and Neural Mnemonics.</p>
          </section>
        </div>
      ),
    },
    privacy: {
      title: "Privacy Policy",
      body: (
        <div className="space-y-6 text-bee-black/80">
          <p className="italic text-sm">Last updated: January 24, 2026</p>
          <section>
            <h4 className="font-display uppercase text-xs tracking-widest text-honey-600 mb-2">Data Foraging</h4>
            <p>We only collect the nectar necessary to process your artifacts. Your raw data is processed in ephemeral hive cells and is never used to train global models without explicit permission.</p>
          </section>
          <section>
            <h4 className="font-display uppercase text-xs tracking-widest text-honey-600 mb-2">Storage Ethics</h4>
            <p>All artifacts are encrypted using industry-standard hexagonal ciphers. Your knowledge base is your hive; we are merely the architects.</p>
          </section>
        </div>
      ),
    },
    terms: {
      title: "Terms of Service",
      body: (
        <div className="space-y-6 text-bee-black/80">
          <p className="italic text-sm">Hive Rules & Regulations</p>
          <section>
            <h4 className="font-display uppercase text-xs tracking-widest text-honey-600 mb-2">User Responsibility</h4>
            <p>Users are responsible for all nectar brought into the hive. You must own the rights to the artifacts you upload for processing.</p>
          </section>
          <section>
            <h4 className="font-display uppercase text-xs tracking-widest text-honey-600 mb-2">Service Availability</h4>
            <p>While we strive for 99.9% hive uptime, maintenance may occur during low-activity seasons. BeePrepared is provided "as is".</p>
          </section>
        </div>
      ),
    },
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
              {/* Backdrop */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                onClick={onClose}
                className="fixed inset-0 bg-bee-black/60 backdrop-blur-md z-[100] cursor-pointer"
              />

              {/* Modal Container */}
              <div className="fixed inset-0 flex items-center justify-center z-[101] pointer-events-none p-4 md:p-6">
                <motion.div
                  initial={{ scale: 0.9, opacity: 0, y: 20 }}
                  animate={{ scale: 1, opacity: 1, y: 0 }}
                  exit={{ scale: 0.9, opacity: 0, y: 20 }}
                  transition={{ type: "spring", damping: 25, stiffness: 300 }}
                  className="w-full max-w-2xl bg-cream border border-wax rounded-[32px] shadow-[0_32px_64px_-12px_rgba(0,0,0,0.3)] overflow-hidden pointer-events-auto flex flex-col max-h-[80vh]"
                >
                {/* Header */}
                <div className="p-8 pb-0 flex items-center justify-between relative">
                  <div className="flex gap-6">
                    {tabs.map((tab) => (
                      <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={`relative font-display text-[10px] uppercase tracking-[0.2em] font-bold py-2 transition-colors cursor-pointer ${
                          activeTab === tab.id ? "text-honey-600" : "text-bee-black/30 hover:text-bee-black/60"
                        }`}
                      >
                        {tab.label}
                        {activeTab === tab.id && (
                          <motion.div
                            layoutId="activeTab"
                            transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
                            className="absolute bottom-0 left-0 right-0 h-0.5 bg-honey-600 rounded-full"
                          />
                        )}
                      </button>
                    ))}
                  </div>

                {/* Close Button - Intentionally centered X */}
                <button
                  onClick={onClose}
                  className="group w-10 h-10 rounded-full bg-bee-black/5 hover:bg-bee-black/10 flex items-center justify-center transition-all duration-300"
                  aria-label="Close modal"
                >
                  <div className="relative w-4 h-4 flex items-center justify-center">
                    <X className="w-full h-full text-bee-black transition-transform duration-300 group-hover:rotate-90" />
                  </div>
                </button>
              </div>

              {/* Title Area */}
              <div className="px-8 pt-8">
                <motion.h3
                  key={`${activeTab}-title`}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="text-4xl font-display uppercase tracking-tighter text-bee-black"
                >
                  {content[activeTab].title}
                </motion.h3>
              </div>

              {/* Content Area */}
              <div className="flex-1 overflow-y-auto p-8 pt-6 custom-scrollbar">
                <motion.div
                  key={activeTab}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  transition={{ duration: 0.2 }}
                  className="prose prose-sm max-w-none"
                >
                  {content[activeTab].body}
                </motion.div>
              </div>

              {/* Footer Decoration */}
              <div className="h-2 bg-gradient-to-r from-honey-400 via-honey-500 to-honey-600 opacity-20" />
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}
