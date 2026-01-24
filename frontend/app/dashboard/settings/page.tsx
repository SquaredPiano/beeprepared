"use client";

import React from "react";
import { User, Bell, Shield, Palette, Zap, Globe, CreditCard } from "lucide-react";
import { motion } from "framer-motion";

const sections = [
  { icon: User, label: "Account", desc: "Manage your personal information and security." },
  { icon: Zap, label: "Pipeline", desc: "Configure autonomous agent behaviors and thresholds." },
  { icon: Palette, label: "Appearance", desc: "Customize the interface theme and motion settings." },
  { icon: Bell, label: "Notifications", desc: "Decide when and how you want to be alerted." },
  { icon: CreditCard, label: "Billing", desc: "Manage your subscription and processing credits." },
  { icon: Shield, label: "Privacy", desc: "Control your data and architectural privacy." },
];

export default function SettingsPage() {
  return (
    <div className="p-12 space-y-12">
      <header className="space-y-4">
        <h1 className="text-5xl font-display uppercase tracking-tighter">System <br /> <span className="italic lowercase opacity-40">Settings</span></h1>
        <p className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-40 max-w-xs leading-relaxed">
          Calibrate your architectural experience and agent autonomy.
        </p>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {sections.map((section, i) => (
          <motion.div
            key={section.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className="group flex items-start gap-6 p-8 glass rounded-[2.5rem] border border-border/40 hover:border-honey-300 transition-all cursor-pointer"
          >
            <div className="w-16 h-16 bg-muted rounded-2xl flex items-center justify-center group-hover:bg-honey-500 group-hover:text-white transition-all duration-500">
              <section.icon className="w-6 h-6" />
            </div>
            <div className="space-y-2 pt-2">
              <h3 className="text-lg font-display font-bold uppercase tracking-tight">{section.label}</h3>
              <p className="text-[10px] uppercase tracking-widest font-bold opacity-40 leading-relaxed max-w-[200px]">
                {section.desc}
              </p>
            </div>
          </motion.div>
        ))}
      </div>

      <div className="p-10 glass rounded-[3rem] border border-border/40 bg-honey-50/10 space-y-8">
        <div className="space-y-2">
          <h2 className="text-xl font-display font-bold uppercase tracking-tight">Danger Zone</h2>
          <p className="text-[10px] uppercase tracking-widest font-bold opacity-40">Irreversible system actions.</p>
        </div>
        <div className="flex flex-wrap gap-4">
          <button className="px-8 py-4 rounded-2xl border border-red-200 text-red-600 text-[10px] font-bold uppercase tracking-widest hover:bg-red-50 transition-all cursor-pointer">
            Purge All Data
          </button>
          <button className="px-8 py-4 rounded-2xl border border-red-200 text-red-600 text-[10px] font-bold uppercase tracking-widest hover:bg-red-50 transition-all cursor-pointer">
            Deactivate Account
          </button>
        </div>
      </div>
    </div>
  );
}
