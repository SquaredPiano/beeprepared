"use client";

import React from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { Sidebar } from "@/components/Sidebar";
import { Footer } from "@/components/Footer";
import { useSidebarStore } from "@/store/useSidebarStore";
import { cn } from "@/lib/utils";
import { HoneyJar } from "@/components/HoneyJar";

export function MainLayoutWrapper({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebarStore();
  const pathname = usePathname();
  const isDashboard = pathname?.startsWith("/dashboard");
  const isProcessing = pathname?.startsWith("/processing");
  const isUpload = pathname === "/upload";

  // Persistent Sidebar for all app views (Dashboard, Processing, Upload)
  const showSidebar = isDashboard || isProcessing || isUpload;

  if (showSidebar) {
    return (
      <div className="flex min-h-screen">
        <Sidebar />
        <main 
          className={cn(
            "flex-1 transition-[padding] duration-300 min-h-screen",
            isCollapsed ? "pl-[100px]" : "pl-[280px]"
          )}
        >
          {children}
        </main>
        {isDashboard && (
          <HoneyJar points={450} maxPoints={1000} level="Worker Bee" isMystery={true} />
        )}
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col">
      <header className="sticky top-0 z-50 w-full glass border-b border-border/40">

          <div className="container mx-auto flex h-20 items-center justify-between px-6">
            <Link href="/" className="group cursor-pointer">
              <Logo showText={true} />
            </Link>
          <nav className="hidden md:flex items-center gap-10 text-[10px] font-bold tracking-[0.2em] uppercase opacity-80">
            <Link href="/dashboard" className="hover:opacity-100 transition-opacity cursor-pointer">Dashboard</Link>
            <Link href="/dashboard/canvas" className="hover:opacity-100 transition-opacity cursor-pointer">Flow</Link>
            <Link href="/upload" className="bg-bee-black text-white px-8 py-3 rounded-full hover:bg-honey-500 transition-all cursor-pointer">
              Start Building
            </Link>
          </nav>
        </div>
      </header>
      <main className="flex-1">
        {children}
      </main>
      <Footer />
    </div>
  );
}
