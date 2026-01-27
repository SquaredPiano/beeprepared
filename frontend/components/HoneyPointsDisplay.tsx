"use client";

import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Hexagon } from "lucide-react";

export function HoneyPointsDisplay() {
  const [balance, setBalance] = useState(0);
  const [prevBalance, setPrevBalance] = useState(0);
  const [diff, setDiff] = useState(0);

  useEffect(() => {
    async function fetchBalance() {
      const b = await api.points.getBalance();
      if (b !== balance) {
        setDiff(b - balance);
        setPrevBalance(balance);
        setBalance(b);
        
        // Hide diff after 3 seconds
        setTimeout(() => setDiff(0), 3000);
      }
    }
    
    fetchBalance();
    const interval = setInterval(fetchBalance, 10000); // Check every 10s
    return () => clearInterval(interval);
  }, [balance]);

  return (
    <div className="relative flex items-center gap-3 px-4 py-2 bg-bee-black rounded-2xl border border-white/10 shadow-lg group cursor-help">
      <div className="p-1.5 bg-honey rounded-lg">
        <Hexagon size={14} className="text-bee-black fill-bee-black/20" />
      </div>
      <div className="flex flex-col">
        <span className="text-[8px] font-bold uppercase tracking-[0.2em] text-white/40 leading-none">Nectar</span>
        <div className="flex items-baseline gap-1 mt-0.5">
          <span className="text-sm font-bold text-white tabular-nums">{balance.toLocaleString()}</span>
          <span className="text-[10px] font-bold text-honey uppercase tracking-widest">Drops</span>
        </div>
      </div>

      <AnimatePresence>
        {diff !== 0 && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: -25 }}
            exit={{ opacity: 0 }}
            className={`absolute top-0 right-0 font-bold text-xs ${diff > 0 ? 'text-green-400' : 'text-red-400'}`}
          >
            {diff > 0 ? `+${diff}` : diff}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Tooltip hint */}
      <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 px-3 py-2 bg-bee-black border border-white/10 rounded-xl text-[9px] font-bold uppercase tracking-widest text-honey opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none z-[100]">
        Earn drops by synthesizing knowledge
      </div>
    </div>
  );
}
