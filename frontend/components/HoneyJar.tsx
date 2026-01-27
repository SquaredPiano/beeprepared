"use client";

import { motion, AnimatePresence } from 'framer-motion';
import { useEffect, useState } from 'react';
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";

interface HoneyJarProps {
  points: number;
  maxPoints: number;
  level: string;
  isMystery?: boolean;
  onReveal?: () => void;
}

export function HoneyJar({ points, maxPoints, level, isMystery, onReveal }: HoneyJarProps) {
  const [revealed, setRevealed] = useState(!isMystery);
  const fillPercentage = (isMystery && !revealed) ? 0 : Math.min((points / maxPoints) * 100, 100);
  const [isAnimating, setIsAnimating] = useState(false);
  
  useEffect(() => {
    if (revealed) {
      setIsAnimating(true);
      const timer = setTimeout(() => setIsAnimating(false), 1000);
      return () => clearTimeout(timer);
    }
  }, [points, revealed]);

  const handleReveal = () => {
    if (isMystery && !revealed) {
      setRevealed(true);
      onReveal?.();
      playSound("complete");
    }
  };
  
  return (
    <motion.div
      className="fixed bottom-8 left-8 z-50"
      initial={{ scale: 0, rotate: -180 }}
      animate={{ scale: 1, rotate: 0 }}
      transition={{ type: 'spring', stiffness: 260, damping: 20 }}
    >
      <div 
        onClick={handleReveal}
        className={cn(
          "relative w-32 h-40 group transition-all duration-500",
          isMystery && !revealed ? "cursor-help scale-110" : "cursor-pointer"
        )}
      >
        {/* Mystery Sparkles */}
        {isMystery && !revealed && (
          <motion.div 
            animate={{ opacity: [0, 1, 0], scale: [0.8, 1.2, 0.8] }}
            transition={{ repeat: Infinity, duration: 2 }}
            className="absolute -inset-4 bg-honey-500/20 blur-2xl rounded-full"
          />
        )}

        {/* Glass Jar SVG */}
        <svg viewBox="0 0 100 150" className="w-full h-full drop-shadow-2xl">
          <defs>
            <linearGradient id="honeyGradient" x1="0%" y1="0%" x2="0%" y2="100%">
              <stop offset="0%" stopColor="#FBBF24" />
              <stop offset="100%" stopColor="#F59E0B" />
            </linearGradient>
          </defs>

          {/* Jar background/body */}
          <path
            d="M 20 20 L 20 120 Q 20 140 40 140 L 60 140 Q 80 140 80 120 L 80 20 Z"
            fill={isMystery && !revealed ? "rgba(0,0,0,0.8)" : "rgba(255, 255, 255, 0.1)"}
            className="backdrop-blur-sm transition-colors duration-1000"
            stroke={isMystery && !revealed ? "#F59E0B" : "rgba(217, 119, 6, 0.3)"}
            strokeWidth="1.5"
          />
          
          {/* Honey fill (animated) */}
          <motion.path
            d={`M 20 ${140 - (fillPercentage * 1.2)} L 20 120 Q 20 140 40 140 L 60 140 Q 80 140 80 120 L 80 ${140 - (fillPercentage * 1.2)} Z`}
            fill="url(#honeyGradient)"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: revealed ? 1 : 0, height: "auto" }}
            transition={{ duration: 1, ease: 'easeOut' }}
          />
          
          {/* Jar lid */}
          <rect x="15" y="10" width="70" height="12" fill={isMystery && !revealed ? "#1A1A1A" : "#92400E"} rx="3" className="transition-colors duration-1000" />
          <rect x="10" y="8" width="80" height="4" fill={isMystery && !revealed ? "#F59E0B" : "#78350F"} rx="2" className="transition-colors duration-1000" />
        </svg>
        
        {/* Points label */}
        <AnimatePresence>
          {revealed && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="absolute inset-0 flex flex-col items-center justify-center pt-4"
            >
              <span className="text-2xl font-display font-bold text-bee-black drop-shadow-sm">
                {points}
              </span>
              <span className="text-[8px] uppercase tracking-widest font-bold opacity-40">Drops</span>
            </motion.div>
          )}
          {!revealed && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 flex flex-col items-center justify-center pt-4"
            >
              <span className="text-4xl font-display font-bold text-honey-500 animate-pulse">?</span>
            </motion.div>
          )}
        </AnimatePresence>
        
        {/* Level badge */}
        <AnimatePresence>
          {revealed && (
            <motion.div 
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              className="absolute -top-2 -right-2 bg-honey-500 text-white text-[10px] font-bold px-3 py-1.5 rounded-full border-2 border-white shadow-lg uppercase tracking-tighter"
            >
              {level}
            </motion.div>
          )}
        </AnimatePresence>
        
        {/* Hover tooltip */}
        <div className="absolute bottom-full mb-4 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-2 group-hover:translate-y-0 bg-bee-black text-white text-[10px] uppercase tracking-widest font-bold rounded-lg px-4 py-3 whitespace-nowrap shadow-2xl">
          {isMystery && !revealed ? "Open Mystery Gift" : `${maxPoints - points} drops to next level`}
        </div>
      </div>
    </motion.div>
  );
}

