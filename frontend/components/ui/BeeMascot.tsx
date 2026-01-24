'use client';

import React, { useEffect } from 'react';
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

export const BeeMascot = () => {
  const { mood, position, message, reset } = useMascotStore();

  useEffect(() => {
    reset();
  }, [reset]);

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
