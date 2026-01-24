"use client";

import React, { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { motion } from "framer-motion";

// Register plugin
if (typeof window !== "undefined") {
  gsap.registerPlugin(MotionPathPlugin);
}
import { 
  ArrowRight, 
  Layers, 
  Cpu, 
  Workflow
} from "lucide-react";
import Link from "next/link";
import { ParticleBackground } from "@/components/ParticleBackground";
import { ScrollReveal } from "@/components/ScrollReveal";
import { FeatureCard } from "@/components/FeatureCard";
import { HoneyJar } from "@/components/HoneyJar";
import { Balancer } from "react-wrap-balancer";

export default function HomePage() {
  const containerRef = useRef(null);
  const honeyRef = useRef(null);
  const beeRef = useRef(null);
  const titleRef = useRef(null);
  const subRef = useRef(null);
  const ctaRef = useRef(null);

    useGSAP(() => {
      // Honey drip animation
      gsap.to(honeyRef.current, {
        y: 15,
        repeat: -1,
        yoyo: true,
        duration: 2.5,
        ease: "power1.inOut",
      });
      
      // Bee flying path (figure-8)
      gsap.to(beeRef.current, {
        duration: 12,
        repeat: -1,
        ease: "none",
        motionPath: {
          path: [
            { x: 0, y: 0 },
            { x: 200, y: -100 },
            { x: 400, y: 0 },
            { x: 200, y: 100 },
            { x: 0, y: 0 }
          ],
          curviness: 2,
        },
      });

      // Ambient hover rotation for bee
      gsap.to(beeRef.current, {
        rotate: 15,
        repeat: -1,
        yoyo: true,
        duration: 2,
        ease: "sine.inOut"
      });

      // Hero entrance
      const tl = gsap.timeline({ defaults: { ease: "expo.out" } });
      tl.from(".reveal-hero", {
        y: 80,
        opacity: 0,
        duration: 2,
        stagger: 0.15,
        delay: 0.5
      })
      .from(beeRef.current, {
        scale: 0,
        opacity: 0,
        duration: 1,
      }, "-=1.5");
    }, { scope: containerRef });


  return (
    <div ref={containerRef} className="relative min-h-screen bg-background overflow-hidden font-sans">
      <ParticleBackground />
      <HoneyJar points={450} maxPoints={1000} level="Worker Bee" isMystery={true} />
      
      {/* Background Pattern */}
      <div className="absolute inset-0 -z-10 opacity-[0.03]">
        <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <pattern id="honeycomb" width="56" height="100" patternUnits="userSpaceOnUse">
            <polygon points="28,0 56,17 56,50 28,67 0,50 0,17" fill="none" stroke="#F59E0B" strokeWidth="1" />
          </pattern>
          <rect width="100%" height="100%" fill="url(#honeycomb)" />
        </svg>
      </div>

      {/* Floating Bee */}
      <div ref={beeRef} className="absolute top-1/4 left-1/4 text-4xl pointer-events-none z-20">🐝</div>

      {/* Hero Section */}
      <section className="container mx-auto px-6 pt-32 pb-24 flex flex-col items-center text-center relative z-10">
        <div className="space-y-12 max-w-6xl">
            <div className="overflow-hidden">
              <h1 ref={titleRef} className="text-7xl md:text-[140px] font-display uppercase leading-[0.8] tracking-tighter reveal-hero">
                Organize Your <br />
                <span ref={honeyRef} className="inline-block font-serif italic lowercase font-normal tracking-normal text-honey-500 py-4">
                  knowledge
                </span> <br />
                Simply
              </h1>
            </div>
            
            <div ref={subRef} className="max-w-3xl mx-auto reveal-hero">
              <p className="text-xl md:text-2xl text-muted-foreground leading-tight font-medium uppercase tracking-tight">
                <Balancer>
                  Transform documents and audio into clean, architectural artifacts.
                  Built for high-performance learning.
                </Balancer>
              </p>
            </div>

            <div ref={ctaRef} className="flex flex-col sm:flex-row items-center justify-center gap-8 pt-4 reveal-hero">

            <Link 
              href="/upload" 
              className="group relative flex items-center gap-6 bg-bee-black text-white px-12 py-6 rounded-full hover:bg-honey-500 transition-all duration-700 shadow-2xl cursor-pointer overflow-hidden"
            >
              <span className="relative z-10 font-display text-sm uppercase tracking-widest font-bold">Start Building</span>
              <div className="relative z-10 w-10 h-10 bg-white/10 rounded-full flex items-center justify-center group-hover:rotate-90 transition-transform duration-700">
                <ArrowRight className="w-5 h-5 text-white" />
              </div>
              <div className="absolute inset-0 bg-gradient-to-r from-honey-600 to-honey-400 translate-y-full group-hover:translate-y-0 transition-transform duration-700 ease-in-out" />
            </Link>
            <Link 
              href="/dashboard" 
              className="px-12 py-6 border border-bee-black/10 rounded-full font-display text-sm uppercase tracking-widest font-bold hover:bg-muted transition-all cursor-pointer backdrop-blur-sm"
            >
              Enter Dashboard
            </Link>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="container mx-auto px-6 py-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
          <ScrollReveal>
            <FeatureCard 
              icon={<Layers className="w-12 h-12 text-honey-600" />}
              title="Cognitive Extraction"
              description="Our foragers scan your artifacts to extract the purest essence of information, removing noise and fluff."
            />
          </ScrollReveal>
          <ScrollReveal>
            <FeatureCard 
              icon={<Workflow className="w-12 h-12 text-honey-600" />}
              title="Architectural Flow"
              description="Visualize the synthesis process through our interactive hive canvas. Watch as bees build your knowledge base."
            />
          </ScrollReveal>
          <ScrollReveal>
            <FeatureCard 
              icon={<Cpu className="w-12 h-12 text-honey-600" />}
              title="Neural Synthesis"
              description="Advanced intelligence layers categorize and structure your content into high-fidelity study artifacts."
            />
          </ScrollReveal>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="py-16 text-center relative">
        <ScrollReveal>
          <div className="container mx-auto px-6 space-y-12 relative z-10">
            <h2 className="text-6xl md:text-[120px] font-display uppercase leading-none tracking-tighter">
              The hive is <br />
              <span className="font-serif italic lowercase opacity-30">waiting for you</span>
            </h2>
            <Link 
              href="/upload" 
              className="inline-block bg-bee-black text-white px-16 py-8 rounded-full font-display text-sm uppercase tracking-widest font-bold hover:bg-honey-500 transition-all shadow-2xl cursor-pointer"
            >
              Begin Ingestion
            </Link>
          </div>
        </ScrollReveal>

        
        {/* Abstract shapes */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[150%] h-[150%] rotate-12 opacity-[0.01] pointer-events-none">
          <svg viewBox="0 0 100 100" className="w-full h-full fill-honey-500">
            <path d="M20 0l17.32 10v20L20 40 2.68 30V10z" />
          </svg>
        </div>
      </section>
    </div>
  );
}
