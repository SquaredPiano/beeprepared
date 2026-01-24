"use client";

import { motion } from 'framer-motion';
import { ReactNode } from 'react';

interface FeatureCardProps {
  icon: ReactNode | string;
  title: string;
  description: string;
}

export function FeatureCard({ icon, title, description }: FeatureCardProps) {
  return (
    <div className="relative group h-full p-8 overflow-visible">
      <motion.div
        whileHover={{ scale: 1.05, y: -5 }}
        className="relative h-full"
      >
        {/* Glassmorphism effect */}
        <div className="absolute inset-0 bg-gradient-to-br from-white/40 to-white/10 backdrop-blur-lg rounded-3xl" />
        <div className="absolute inset-0 bg-gradient-to-br from-honey-500/10 to-transparent rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity" />
        
        {/* Content */}
        <div className="relative p-10 border border-white/20 rounded-3xl shadow-[0_20px_50px_rgba(0,0,0,0.1)] h-full flex flex-col items-start gap-4 bg-white/5">
          <div className="text-5xl mb-2">{icon}</div>
          <h3 className="text-2xl font-display uppercase tracking-tight">{title}</h3>
          <p className="text-muted-foreground leading-relaxed">{description}</p>
        </div>
        
        {/* Glow effect */}
        <div className="absolute inset-0 rounded-3xl opacity-0 group-hover:opacity-100 transition-opacity blur-2xl bg-honey-500/20 -z-10" />
      </motion.div>
    </div>
  );
}
