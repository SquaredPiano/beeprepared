"use client";

import React, { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { useGSAP } from "@gsap/react";

export function FlyingMascot() {
  const beeRef = useRef<HTMLDivElement>(null);
  const [isHovered, setIsHovered] = useState(false);
  const [isVisible, setIsVisible] = useState(false);
  const [clickCount, setClickCount] = useState(0);

  const handleClick = () => {
    setClickCount((prev) => prev + 1);
    
    // Playful interaction: do a loop-de-loop
    if (beeRef.current) {
      gsap.to(beeRef.current, {
        rotate: "+=360",
        scale: 1.5,
        duration: 0.6,
        ease: "back.out(1.7)",
        onComplete: () => {
          gsap.to(beeRef.current, { scale: 1, duration: 0.3 });
        }
      });
    }
  };

  useGSAP(() => {
    if (!beeRef.current) return;

    // Random appearance/disappearance behavior
    const randomAppearance = () => {
      const shouldAppear = Math.random() > 0.3; // 70% chance to appear
      const delay = Math.random() * 8000 + 3000; // 3-11 seconds

      setTimeout(() => {
        if (shouldAppear && !isVisible) {
          setIsVisible(true);
          // Enter from left side
          gsap.fromTo(beeRef.current,
            { x: -150, y: 80, opacity: 0 },
            {
              x: 120,
              y: 100,
              opacity: 1,
              duration: 2,
              ease: "power2.out",
              onComplete: () => {
                // Stay for a while, then maybe leave
                setTimeout(() => {
                  if (Math.random() > 0.5) {
                    // Leave the screen
                    gsap.to(beeRef.current, {
                      x: -150,
                      opacity: 0,
                      duration: 1.5,
                      ease: "power2.in",
                      onComplete: () => {
                        setIsVisible(false);
                        randomAppearance();
                      }
                    });
                  } else {
                    randomAppearance();
                  }
                }, Math.random() * 10000 + 5000); // Stay 5-15 seconds
              }
            }
          );
        } else {
          randomAppearance();
        }
      }, delay);
    };

    // Start the random appearance cycle
    randomAppearance();

    // Constant small jitter (wing vibration effect) when visible
    if (isVisible) {
      gsap.to(".bee-body", {
        y: "+=3",
        repeat: -1,
        yoyo: true,
        duration: 0.08,
        ease: "none"
      });
    }

  }, { dependencies: [isVisible] });

  // Hide bee when mouse hovers over it (like real life!)
  useEffect(() => {
    if (isHovered && beeRef.current) {
      gsap.to(beeRef.current, {
        x: -150,
        opacity: 0,
        duration: 0.8,
        ease: "power2.in",
        onComplete: () => {
          setIsVisible(false);
          setIsHovered(false);
        }
      });
    }
  }, [isHovered]);

  if (!isVisible) return null;

  return (
    <div 
      ref={beeRef} 
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      className="fixed z-40 w-20 h-20 flex items-center justify-center select-none cursor-pointer transition-transform duration-300"
      style={{ left: '0', top: '0', pointerEvents: 'auto', overflow: 'visible' }}
    >
      <div className="relative w-full h-full bee-container">
        {/* Simple Bee SVG Mascot */}
        <svg viewBox="0 0 100 100" className="w-full h-full drop-shadow-[0_10px_20px_rgba(0,0,0,0.2)]">
          {/* Wings */}
          <ellipse cx="40" cy="40" rx="15" ry="25" fill="#E0E0E0" opacity="0.8" className="animate-[pulse_0.1s_infinite] origin-bottom-right rotate-[-20deg]" />
          <ellipse cx="60" cy="40" rx="15" ry="25" fill="#E0E0E0" opacity="0.8" className="animate-[pulse_0.1s_infinite] origin-bottom-left rotate-[20deg]" />
          
          {/* Body */}
          <g className="bee-body">
            <ellipse cx="50" cy="60" rx="25" ry="20" fill="#FFB800" stroke="#000" strokeWidth="3" />
            {/* Stripes */}
            <rect x="35" y="50" width="4" height="20" fill="#000" rx="2" transform="rotate(-5 35 50)" />
            <rect x="48" y="48" width="4" height="24" fill="#000" rx="2" />
            <rect x="61" y="50" width="4" height="20" fill="#000" rx="2" transform="rotate(5 61 50)" />
            {/* Eyes */}
            <circle cx="68" cy="55" r="4" fill="#000" />
            <circle cx="78" cy="55" r="4" fill="#000" />
            {/* Antennae */}
            <path d="M68 45 C 68 45, 72 30, 75 35" stroke="#000" strokeWidth="2" fill="none" />
            <path d="M78 45 C 78 45, 82 30, 85 35" stroke="#000" strokeWidth="2" fill="none" />
          </g>
        </svg>

        {/* Playful tooltip on click */}
        {clickCount > 0 && (
          <div className="absolute -top-12 left-1/2 -translate-x-1/2 bg-bee-black text-honey text-[10px] font-black uppercase py-2 px-4 rounded-md whitespace-nowrap animate-bounce shadow-xl border border-honey/20">
            {clickCount % 3 === 0 ? "Bzzz! Synthesis engaged!" : clickCount % 2 === 0 ? "Building your hive!" : "Ready to master?"}
          </div>
        )}
      </div>
    </div>
  );
}
