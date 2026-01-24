"use client";

import { motion } from 'framer-motion';
import { useEffect, useState } from 'react';

interface HoneyJarProps {
  points: number;
  maxPoints: number;
  level: string;
}

export function HoneyJar({ points, maxPoints, level }: HoneyJarProps) {
  const fillPercentage = Math.min((points / maxPoints) * 100, 100);
  const [isAnimating, setIsAnimating] = useState(false);
  
  useEffect(() => {
    setIsAnimating(true);
    const timer = setTimeout(() => setIsAnimating(false), 1000);
    return () => clearTimeout(timer);
  }, [points]);
  
  return (
    <motion.div
      className="fixed bottom-8 right-8 z-50"
      initial={{ scale: 0, rotate: -180 }}
      animate={{ scale: 1, rotate: 0 }}
      transition={{ type: 'spring', stiffness: 260, damping: 20 }}
    >
      <div className="relative w-32 h-40 cursor-pointer group">
        {/* Glass Jar SVG */}
        <svg viewBox="0 0 100 150" className="w-full h-full drop-shadow-2xl">
          <defs>
            <linearGradient id="honeyGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#FBBF24" />
              <stop offset="100%" stopColor="#F59E0B" />
            </linearGradient>
            <filter id="glow">
              <feGaussianBlur stdDeviation="2.5" result="coloredBlur"/>
              <feMerge>
                <feMergeNode in="coloredBlur"/>
                <feMergeNode in="SourceGraphic"/>
              </feMerge>
            </filter>
          </defs>

          {/* Jar background/body */}
          <path
            d="M 20 20 L 20 120 Q 20 140 40 140 L 60 140 Q 80 140 80 120 L 80 20 Z"
            fill="rgba(255, 255, 255, 0.1)"
            className="backdrop-blur-sm"
            stroke="rgba(217, 119, 6, 0.3)"
            strokeWidth="1.5"
          />
          
          {/* Honey fill (animated) */}
          <motion.path
            d={`M 20 ${140 - (fillPercentage * 1.2)} L 20 120 Q 20 140 40 140 L 60 140 Q 80 140 80 120 L 80 ${140 - (fillPercentage * 1.2)} Z`}
            fill="url(#honeyGradient)"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, ease: 'easeOut' }}
          />
          
          {/* Jar lid */}
          <rect x="15" y="10" width="70" height="12" fill="#92400E" rx="3" />
          <rect x="10" y="8" width="80" height="4" fill="#78350F" rx="2" />
        </svg>
        
        {/* Points label */}
        <motion.div
          className="absolute inset-0 flex flex-col items-center justify-center pt-4"
          animate={isAnimating ? { scale: [1, 1.2, 1] } : {}}
        >
          <span className="text-2xl font-display font-bold text-bee-black drop-shadow-sm">
            {points}
          </span>
          <span className="text-[8px] uppercase tracking-widest font-bold opacity-40">Drops</span>
        </motion.div>
        
        {/* Level badge */}
        <div className="absolute -top-2 -right-2 bg-honey-500 text-white text-[10px] font-bold px-3 py-1.5 rounded-full border-2 border-white shadow-lg uppercase tracking-tighter">
          {level}
        </div>
        
        {/* Hover tooltip */}
        <div className="absolute bottom-full mb-4 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-2 group-hover:translate-y-0 bg-bee-black text-white text-[10px] uppercase tracking-widest font-bold rounded-lg px-4 py-3 whitespace-nowrap shadow-2xl">
          {maxPoints - points} drops to next level
        </div>
      </div>
    </motion.div>
  );
}
