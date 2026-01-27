"use client";

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Github, ExternalLink, LifeBuoy, Bug, Lightbulb } from "lucide-react";

const GITHUB_ISSUES_URL = "https://github.com/SquaredPiano/beeprepared/issues";

interface SupportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SupportModal({ isOpen, onClose }: SupportModalProps) {
  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-bee-black/40 backdrop-blur-md z-[200] cursor-pointer"
          />
          <div className="fixed inset-0 flex items-center justify-center z-[201] pointer-events-none p-4">
            <motion.div
              initial={{ scale: 0.9, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 20 }}
              className="w-full max-w-lg bg-cream border border-wax rounded-[32px] shadow-2xl overflow-hidden pointer-events-auto flex flex-col"
            >
              <div className="p-8 flex items-center justify-between border-b border-wax/50">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-2xl bg-honey/10 flex items-center justify-center">
                    <LifeBuoy className="text-honey-600 w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-lg font-display uppercase font-bold tracking-tight text-bee-black">
                      Hive Support
                    </h3>
                    <p className="text-[10px] uppercase tracking-widest text-bee-black/40 font-bold">
                      Community-Driven Support
                    </p>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="w-10 h-10 rounded-full bg-bee-black/5 hover:bg-bee-black/10 flex items-center justify-center transition-all group cursor-pointer"
                >
                  <X className="w-4 h-4 text-bee-black transition-transform group-hover:rotate-90" />
                </button>
              </div>

              <div className="p-8 space-y-6">
                <p className="text-sm text-bee-black/70 leading-relaxed">
                  BeePrepared is an open-source project. For bugs, feature requests, or questions,
                  please open an issue on our GitHub repository.
                </p>

                <div className="grid grid-cols-1 gap-4">
                  <a
                    href={`${GITHUB_ISSUES_URL}/new?template=bug_report.md`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-4 p-6 rounded-2xl border border-wax bg-white/50 hover:bg-white hover:shadow-xl hover:scale-[1.02] transition-all group"
                  >
                    <div className="w-12 h-12 rounded-xl bg-red-50 flex items-center justify-center group-hover:bg-red-100 transition-colors">
                      <Bug className="text-red-600 w-6 h-6" />
                    </div>
                    <div className="flex-1">
                      <h4 className="font-bold text-bee-black text-sm uppercase tracking-wide">Report a Bug</h4>
                      <p className="text-xs text-bee-black/50">Something not working correctly?</p>
                    </div>
                    <ExternalLink className="w-4 h-4 text-bee-black/20 group-hover:text-bee-black/40" />
                  </a>

                  <a
                    href={`${GITHUB_ISSUES_URL}/new?template=feature_request.md`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-4 p-6 rounded-2xl border border-wax bg-white/50 hover:bg-white hover:shadow-xl hover:scale-[1.02] transition-all group"
                  >
                    <div className="w-12 h-12 rounded-xl bg-honey/10 flex items-center justify-center group-hover:bg-honey/20 transition-colors">
                      <Lightbulb className="text-honey-600 w-6 h-6" />
                    </div>
                    <div className="flex-1">
                      <h4 className="font-bold text-bee-black text-sm uppercase tracking-wide">Feature Request</h4>
                      <p className="text-xs text-bee-black/50">Have an idea to improve BeePrepared?</p>
                    </div>
                    <ExternalLink className="w-4 h-4 text-bee-black/20 group-hover:text-bee-black/40" />
                  </a>

                  <a
                    href={GITHUB_ISSUES_URL}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-4 p-6 rounded-2xl border border-wax bg-white/50 hover:bg-white hover:shadow-xl hover:scale-[1.02] transition-all group"
                  >
                    <div className="w-12 h-12 rounded-xl bg-bee-black/5 flex items-center justify-center group-hover:bg-bee-black/10 transition-colors">
                      <Github className="text-bee-black w-6 h-6" />
                    </div>
                    <div className="flex-1">
                      <h4 className="font-bold text-bee-black text-sm uppercase tracking-wide">Browse Issues</h4>
                      <p className="text-xs text-bee-black/50">View existing issues and discussions</p>
                    </div>
                    <ExternalLink className="w-4 h-4 text-bee-black/20 group-hover:text-bee-black/40" />
                  </a>
                </div>

                <div className="bg-honey/5 border border-honey/10 rounded-2xl p-5 text-center">
                  <p className="text-xs text-honey-700 font-medium leading-relaxed">
                    Thank you for helping make BeePrepared better!
                    Our maintainers review issues regularly.
                  </p>
                </div>
              </div>

              <div className="h-1.5 bg-gradient-to-r from-honey-400 via-honey-500 to-honey-600 opacity-30" />
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}

