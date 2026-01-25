'use client';

import React, { useEffect, useRef } from 'react';
import Image from 'next/image';
import { motion, AnimatePresence, Variants } from 'framer-motion';
import { useMascotStore } from '@/store/useMascotStore';
import { BubbleTail } from './BubbleTail';

const positionVariants: Variants = {
  'bottom-right': { x: 'calc(100vw - 140px)', y: 'calc(100vh - 140px)', scale: 1 },
  'center': { x: 'calc(50vw - 64px)', y: 'calc(50vh - 64px)', scale: 1.5 },
  'top-right': { x: 'calc(100vw - 120px)', y: '120px', scale: 0.8 },
  'hidden': { x: 'calc(100vw + 200px)', y: 'calc(100vh + 200px)', scale: 0 }
};

const hoverAnimation = {
  y: [0, -15, 0],
  rotate: [0, 2, -2, 0],
  transition: {
    duration: 3,
    repeat: Infinity,
    ease: "easeInOut"
  }
};

// Random interval choices in ms (5, 15, or 60 minutes)
const INTERVAL_OPTIONS = [5 * 60 * 1000, 15 * 60 * 1000, 60 * 60 * 1000];

export const BeeMascot = () => {
  const { mood, position, message, reset, say, flyTo } = useMascotStore();
  const lastIntervalRef = useRef<number | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Initial fly-in animation on mount
  useEffect(() => {
    // Start hidden, then fly in
    flyTo('hidden');
    
    const flyInTimer = setTimeout(() => {
      flyTo('bottom-right');
      say("Welcome back! Ready to study?", 4000);
    }, 500);

    return () => clearTimeout(flyInTimer);
  }, []);

  // Random interval appearances (no consecutive same interval)
  useEffect(() => {
    const scheduleNextAppearance = () => {
      // Pick a random interval that's different from the last one
      let availableIntervals = INTERVAL_OPTIONS.filter(i => i !== lastIntervalRef.current);
      if (availableIntervals.length === 0) availableIntervals = INTERVAL_OPTIONS;
      
      const nextInterval = availableIntervals[Math.floor(Math.random() * availableIntervals.length)];
      lastIntervalRef.current = nextInterval;

      timeoutRef.current = setTimeout(() => {
        // Fly in with a random message
        const messages = [
          "Taking a break? Don't forget to review!",
          "You're doing great! Keep it up!",
          "Pro tip: Space repetition helps memory!",
          "Need help? I'm here for you!",
          "Time flies when you're learning!"
        ];
        const randomMessage = messages[Math.floor(Math.random() * messages.length)];
        
        flyTo('bottom-right');
        say(randomMessage, 5000);
        
        // Schedule next appearance
        scheduleNextAppearance();
      }, nextInterval);
    };

    // Start the interval cycle after initial fly-in
    const startTimer = setTimeout(() => {
      scheduleNextAppearance();
    }, 10000);

    return () => {
      clearTimeout(startTimer);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [flyTo, say]);

  return (
    <div className="fixed top-0 left-0 pointer-events-none z-[100] w-32 h-32">
      <motion.div
        initial="hidden"
        animate={position}
        variants={positionVariants}
        transition={{ 
          type: "spring", 
          stiffness: 60, 
          damping: 15, 
          mass: 1.2 
        }}
        className="relative w-full h-full"
      >
        <AnimatePresence>
          {message && (
            <motion.div
              initial={{ opacity: 0, y: 10, scale: 0.8 }}
              animate={{ opacity: 1, y: -20, scale: 1 }}
              exit={{ opacity: 0, scale: 0.5 }}
              className="absolute -top-24 right-0 min-w-[180px] max-w-[220px] bg-white border border-honey/20 
                         shadow-[0_4px_20px_-2px_rgba(252,211,79,0.3)] 
                         rounded-2xl p-4 pointer-events-auto flex flex-col items-center"
            >
              <p className="font-sans text-sm font-medium text-bee-black leading-tight text-center">
                {message}
              </p>
              <div className="absolute -bottom-[17px] right-8">
                <BubbleTail />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <motion.div
          animate={mood === 'celebrating' ? {
            rotate: [0, -10, 10, -10, 0],
            scale: [1, 1.2, 1],
            y: [0, -30, 0]
          } : hoverAnimation}
          transition={mood === 'celebrating' ? { duration: 0.8 } : undefined}
          whileHover={{ scale: 1.1, rotate: 5 }}
          className="w-full h-full relative cursor-pointer pointer-events-auto"
          onClick={() => useMascotStore.getState().say("Keep up the great work!")}
        >
          <div className="absolute -bottom-4 left-1/4 w-1/2 h-2 bg-black/20 blur-md rounded-full" />
          
          <Image 
            src="/logo.png"
            alt="BeePrepared Mascot"
            width={128}
            height={128}
            className="drop-shadow-lg object-contain"
            priority
            onError={(e) => {
              // Fallback if image is missing
              const target = e.target as HTMLImageElement;
              target.src = "https://img.icons8.com/color/96/bee.png"; 
            }}
          />
        </motion.div>
      </motion.div>
    </div>
  );
};
