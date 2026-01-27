"use client";

import { useState, useEffect, useCallback, createContext, useContext } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Balancer } from "react-wrap-balancer";
import { X } from "lucide-react";

type MascotMood = 'idle' | 'happy' | 'celebrating' | 'encouraging' | 'thinking';

interface MascotContextType {
  say: (message: string, mood?: MascotMood, duration?: number) => void;
}

const MascotContext = createContext<MascotContextType | undefined>(undefined);

export function useMascot() {
  const context = useContext(MascotContext);
  if (!context) throw new Error("useMascot must be used within MascotProvider");
  return context;
}

export function MascotProvider({ children }: { children: React.ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const [mood, setMood] = useState<MascotMood>('idle');
  const [isVisible, setIsVisible] = useState(false);

  const say = useCallback((msg: string, newMood: MascotMood = 'happy', duration: number = 5000) => {
    setMessage(msg);
    setMood(newMood);
    setIsVisible(true);
    
    if (duration > 0) {
      setTimeout(() => {
        setIsVisible(false);
      }, duration);
    }
  }, []);

  return (
    <MascotContext.Provider value={{ say }}>
      {children}
      <AnimatePresence>
        {isVisible && (
          <motion.div
            initial={{ opacity: 0, y: 50, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.9 }}
            className="fixed bottom-8 right-8 z-[200] flex items-end gap-4 pointer-events-none"
          >
            {/* Speech Bubble */}
            <motion.div 
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              className="bg-bee-black text-cream p-6 rounded-[2rem] rounded-br-none shadow-2xl max-w-xs border border-white/10 relative mb-12 pointer-events-auto"
            >
              <p className="text-xs font-bold uppercase tracking-widest leading-relaxed">
                <Balancer>{message}</Balancer>
              </p>
              <button 
                onClick={() => setIsVisible(false)}
                className="absolute -top-2 -right-2 bg-honey text-bee-black p-1 rounded-full shadow-lg"
              >
                <X size={10} />
              </button>
              {/* Triangle Tail */}
              <div className="absolute bottom-0 right-0 translate-y-full w-4 h-4 border-l-[16px] border-l-bee-black border-b-[16px] border-b-transparent" />
            </motion.div>

            {/* Mascot Character */}
            <motion.div
              animate={{ 
                y: [0, -10, 0],
                rotate: mood === 'celebrating' ? [0, 10, -10, 0] : [0, 2, -2, 0]
              }}
              transition={{ 
                duration: mood === 'celebrating' ? 0.5 : 4, 
                repeat: Infinity,
                ease: "easeInOut"
              }}
              className="text-6xl filter drop-shadow-2xl select-none pointer-events-auto cursor-help"
              onClick={() => say("I'm here to help you build your knowledge hive!", 'happy')}
            >
              {mood === 'idle' && '🐝'}
              {mood === 'happy' && '🐝'}
              {mood === 'celebrating' && '🎉'}
              {mood === 'encouraging' && '✨'}
              {mood === 'thinking' && '🤔'}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </MascotContext.Provider>
  );
}
