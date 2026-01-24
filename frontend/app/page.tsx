"use client";

import React, { useRef } from "react";
import { useGSAP } from "@gsap/react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { 
  ArrowRight, 
  Cpu, 
  Workflow,
  Hexagon,
  Search,
  FileText,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { Balancer } from "react-wrap-balancer";
import { FlyingMascot } from "@/components/ui/flying-mascot";
import { Footer } from "@/components/Footer";

if (typeof window !== "undefined") {
  gsap.registerPlugin(ScrollTrigger);
}

// --- Components ---

const SharpCard = ({ icon, title, description }: { icon: React.ReactNode, title: string, description: string }) => (
  <div className="sharp-card group bg-white border-2 border-bee-black p-8 relative transition-all duration-300 flex flex-col justify-between h-[400px] w-[320px] shrink-0 shadow-[6px_6px_0px_0px_#0F0F0F] hover:shadow-[10px_10px_0px_0px_#FFB800] hover:-translate-y-1">
    <div>
      <div className="mb-6 p-3 bg-honey-100 inline-block border-2 border-bee-black">
        {icon}
      </div>
      <h3 className="text-2xl font-black uppercase tracking-tighter mb-3 text-bee-black leading-none">{title}</h3>
      <p className="text-bee-black/60 font-medium leading-snug text-sm">
        {description}
      </p>
    </div>
  </div>
);

// --- Main Page ---

export default function LandingPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const heroRef = useRef<HTMLDivElement>(null);

  useGSAP(() => {
    // Hero parallax - content moves up faster than scroll
    if (heroRef.current) {
      gsap.to(".hero-content", {
        yPercent: -50,
        opacity: 0,
        ease: "none",
        scrollTrigger: {
          trigger: heroRef.current,
          start: "top top",
          end: "bottom top",
          scrub: true,
        }
      });
    }

    // Reveal animations for each section
    gsap.utils.toArray<HTMLElement>(".scroll-section").forEach((section) => {
      const content = section.querySelector(".section-content");
      const image = section.querySelector(".section-image");
      
      if (content) {
        gsap.from(content.querySelectorAll(".reveal"), {
          y: 80,
          opacity: 0,
          duration: 1,
          stagger: 0.15,
          ease: "power3.out",
          scrollTrigger: {
            trigger: section,
            start: "top 75%",
            end: "top 25%",
            toggleActions: "play none none reverse",
          }
        });
      }

      if (image) {
        gsap.from(image, {
          x: image.classList.contains("from-left") ? -100 : 100,
          opacity: 0,
          duration: 1.2,
          ease: "power3.out",
          scrollTrigger: {
            trigger: section,
            start: "top 70%",
            end: "top 30%",
            toggleActions: "play none none reverse",
          }
        });
      }
    });

    // Horizontal scroll for features cards
    const cardsContainer = document.querySelector(".cards-track");
    const cardsWrapper = document.querySelector(".cards-wrapper");
    if (cardsContainer && cardsWrapper) {
      const cards = cardsContainer.querySelectorAll(".sharp-card");
      const totalWidth = (cards.length * 340) - window.innerWidth + 160;
      
      gsap.to(cardsContainer, {
        x: -totalWidth,
        ease: "none",
        scrollTrigger: {
          trigger: cardsWrapper,
          start: "top top",
          end: () => `+=${totalWidth}`,
          scrub: 1,
          pin: true,
          anticipatePin: 1,
        }
      });
    }

    // CTA section reveal
    gsap.from(".cta-content", {
      y: 100,
      opacity: 0,
      duration: 1.5,
      ease: "power3.out",
      scrollTrigger: {
        trigger: ".cta-section",
        start: "top 60%",
        toggleActions: "play none none reverse",
      }
    });

  }, { scope: containerRef });

  return (
    <div ref={containerRef} className="bg-cream text-bee-black selection:bg-honey selection:text-bee-black">
      {/* Fixed Video Background */}
      <div className="fixed inset-0 z-0">
        <video 
          autoPlay 
          muted 
          loop 
          playsInline
          preload="auto"
          className="w-full h-full object-cover"
          style={{ width: '100%', height: '100%' }}
        >
          <source src="/assets/hero-bg.mp4" type="video/mp4" />
        </video>
        <div className="absolute inset-0 bg-gradient-to-b from-cream/80 via-cream/60 to-cream" />
      </div>
      
      <FlyingMascot />

      {/* Main scrollable content */}
      <main className="relative z-10">
        
        {/* Section 00: Hero */}
        <section ref={heroRef} className="min-h-screen flex items-center justify-center relative pt-20">
          <div className="hero-content text-center w-full max-w-6xl px-8">
            <h1 className="text-[14vw] md:text-[10vw] font-black leading-[0.85] tracking-tighter uppercase mb-8 text-bee-black">
              Study <br /> 
              <span className="font-serif italic lowercase font-normal text-honey-600">Smarter</span> <br /> 
              Together
            </h1>
            <p className="text-sm md:text-base font-bold uppercase tracking-[0.25em] max-w-xl mx-auto mb-12 text-bee-black/50 leading-relaxed cursor-text">
              <Balancer>
                Convert lectures and notes into high-fidelity study artifacts. 
                The intentional workspace for the top 1%.
              </Balancer>
            </p>
            <div className="flex justify-center">
              <Link 
                href="/upload" 
                className="group bg-honey text-bee-black px-10 py-5 font-black uppercase tracking-[0.15em] text-xs hover:bg-bee-black hover:text-white transition-all duration-300 shadow-[6px_6px_0px_0px_#0F0F0F] cursor-pointer"
              >
                Get Started
              </Link>
            </div>
          </div>
          
          {/* Scroll indicator */}
          <div className="absolute bottom-12 left-1/2 -translate-x-1/2 flex flex-col items-center gap-3 animate-bounce">
            <div className="w-px h-8 bg-bee-black/20" />
          </div>
        </section>

        {/* Section 01: Ingestion */}
        <section className="scroll-section min-h-screen flex items-center py-32 px-8 md:px-16 lg:px-24 bg-cream/95 backdrop-blur-sm">
          <div className="max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-24 items-center">
            <div className="section-content space-y-8">
              <div className="reveal text-honey-600 font-black uppercase tracking-[0.3em] text-[10px]">
                01 — Artifact Ingestion
              </div>
              <h2 className="reveal text-5xl md:text-6xl lg:text-7xl font-black uppercase leading-[0.9] tracking-tighter">
                Raw <br /> <span className="text-honey-500">Noise</span> to <br /> Essence
              </h2>
              <p className="reveal text-base md:text-lg font-medium opacity-60 max-w-md leading-relaxed cursor-text">
                Upload PDFs, Audio, or Video. Our hive foragers scan every frame and frequency to extract the core intelligence of your material.
              </p>
            </div>
            <div className="section-image relative hidden lg:block">
              <div className="border-[3px] border-bee-black shadow-[12px_12px_0px_0px_#FFB800] overflow-hidden aspect-4/3 bg-bee-black/5">
                <img 
                  src="https://images.unsplash.com/photo-1516321318423-f06f85e504b3?q=80&w=2070&auto=format&fit=crop" 
                  alt="Artifact Ingestion" 
                  className="w-full h-full object-cover"
                />
              </div>
              <div className="absolute -bottom-6 -left-6 w-24 h-24 bg-honey border-[3px] border-bee-black flex items-center justify-center shadow-[4px_4px_0px_0px_#0F0F0F]">
                <Search size={36} className="text-bee-black" strokeWidth={2.5} />
              </div>
            </div>
          </div>
        </section>

        {/* Section 02: Synthesis */}
        <section className="scroll-section min-h-screen flex items-center py-32 px-8 md:px-16 lg:px-24 bg-bee-black text-white">
          <div className="max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-24 items-center">
            <div className="section-image from-left order-2 lg:order-1 relative hidden lg:block">
              <div className="border-[3px] border-honey shadow-[12px_12px_0px_0px_rgba(255,255,255,0.1)] overflow-hidden aspect-4/3 bg-white/5">
                <img 
                  src="https://images.unsplash.com/photo-1550751827-4bd374c3f58b?q=80&w=2070&auto=format&fit=crop" 
                  alt="Cognitive Synthesis" 
                  className="w-full h-full object-cover opacity-70 grayscale"
                />
              </div>
              <div className="absolute -top-6 -right-6 w-24 h-24 bg-honey border-[3px] border-bee-black flex items-center justify-center shadow-[4px_4px_0px_0px_#FFB800]">
                <Cpu size={36} className="text-bee-black" strokeWidth={2.5} />
              </div>
            </div>
            <div className="section-content space-y-8 order-1 lg:order-2">
              <div className="reveal text-honey font-black uppercase tracking-[0.3em] text-[10px]">
                02 — Cognitive Synthesis
              </div>
              <h2 className="reveal text-5xl md:text-6xl lg:text-7xl font-black uppercase leading-[0.9] tracking-tighter">
                Structural <br /> <span className="text-honey">Purity</span>
              </h2>
              <p className="reveal text-base md:text-lg font-medium opacity-60 max-w-md leading-relaxed cursor-text">
                Our synthesis engine reformulates chaotic data into a structured honeycomb architecture. Visualize connections you never knew existed.
              </p>
            </div>
          </div>
        </section>

        {/* Section 03: Mastery */}
        <section className="scroll-section min-h-screen flex items-center py-32 px-8 md:px-16 lg:px-24 bg-cream/95 backdrop-blur-sm">
          <div className="max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-2 gap-16 lg:gap-24 items-center">
            <div className="section-content space-y-8">
              <div className="reveal text-honey-600 font-black uppercase tracking-[0.3em] text-[10px]">
                03 — Total Mastery
              </div>
              <h2 className="reveal text-5xl md:text-6xl lg:text-7xl font-black uppercase leading-[0.9] tracking-tighter">
                The Final <br /> <span className="text-honey-500">Artifact</span>
              </h2>
              <p className="reveal text-base md:text-lg font-medium opacity-60 max-w-md leading-relaxed cursor-text">
                Generated flashcards, summaries, and mock exams designed for retention. 60% less time spent. 100% more understood.
              </p>
            </div>
            <div className="section-image relative hidden lg:block">
              <div className="border-[3px] border-bee-black shadow-[12px_12px_0px_0px_#FFB800] overflow-hidden aspect-4/3 bg-bee-black/5">
                <img 
                  src="https://images.unsplash.com/photo-1434030216411-0b793f4b4173?q=80&w=2070&auto=format&fit=crop" 
                  alt="Final Artifact" 
                  className="w-full h-full object-cover"
                />
              </div>
              <div className="absolute -bottom-6 -right-6 w-24 h-24 bg-honey border-[3px] border-bee-black flex items-center justify-center shadow-[4px_4px_0px_0px_#0F0F0F]">
                <Zap size={36} className="text-bee-black" strokeWidth={2.5} />
              </div>
            </div>
          </div>
        </section>

        {/* Section 04: Features - Horizontal Scroll */}
        <section className="cards-wrapper min-h-screen bg-cream/95 backdrop-blur-sm">
          <div className="h-screen flex flex-col justify-center">
            <div className="container mx-auto px-8 mb-12 pt-24">
              <div className="text-honey-600 font-black uppercase tracking-[0.3em] text-[10px] mb-3">
                Capabilities
              </div>
              <h2 className="text-4xl md:text-5xl lg:text-6xl font-black uppercase tracking-tighter leading-none">
                Tools for Mastery
              </h2>
            </div>
            <div className="overflow-visible py-8">
              <div className="cards-track flex px-8 gap-8 w-max pb-16">
                <SharpCard 
                  icon={<Cpu className="w-8 h-8" strokeWidth={2.5} />}
                  title="Synthesis"
                  description="Our engine processes complex data and reformulates it into clear, actionable study units."
                />
                <SharpCard 
                  icon={<Workflow className="w-8 h-8" strokeWidth={2.5} />}
                  title="Flow"
                  description="Visualize your knowledge progress through an interactive canvas designed for clarity."
                />
                <SharpCard 
                  icon={<Zap className="w-8 h-8" strokeWidth={2.5} />}
                  title="Velocity"
                  description="Reduce study time by 60% with automatically generated flashcards and summaries."
                />
                <SharpCard 
                  icon={<FileText className="w-8 h-8" strokeWidth={2.5} />}
                  title="Artifacts"
                  description="Export your synthesized knowledge into multiple high-fidelity formats ready for review."
                />
                <SharpCard 
                  icon={<Hexagon className="w-8 h-8" strokeWidth={2.5} />}
                  title="Structure"
                  description="Build a persistent mental model of your subject matter with our honeycomb architecture."
                />
              </div>
            </div>
          </div>
        </section>

        {/* Section 05: Final CTA */}
        <section className="cta-section min-h-screen flex flex-col bg-honey">
          <div className="flex-1 flex flex-col items-center justify-center px-8 py-24 text-center relative overflow-hidden">
            <div className="cta-content z-10 max-w-4xl space-y-10">
              <h2 className="text-6xl md:text-7xl lg:text-[8vw] font-black uppercase leading-[0.8] tracking-tighter">
                The Hive <br /> Is Open
              </h2>
              <div className="h-1 w-24 bg-bee-black mx-auto" />
              <p className="text-lg md:text-xl font-bold uppercase tracking-widest max-w-xl mx-auto opacity-70 leading-relaxed cursor-text">
                Stop drowning in information. Start building your knowledge architecture today.
              </p>
              <div className="flex justify-center pt-6">
                <Link 
                  href="/upload" 
                  className="group bg-bee-black text-white px-12 py-6 font-black uppercase tracking-[0.2em] text-sm hover:bg-honey hover:text-white transition-all duration-300 shadow-[8px_8px_0px_0px_rgba(255,255,255,0.8)] cursor-pointer"
                >
                  Initialize Synthesis
                </Link>
              </div>
            </div>
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-[30vw] font-black uppercase opacity-[0.04] select-none pointer-events-none leading-none">
              BEE
            </div>
          </div>

          <Footer />
        </section>

      </main>
    </div>
  );
}
