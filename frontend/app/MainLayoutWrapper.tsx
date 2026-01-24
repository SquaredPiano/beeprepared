"use client";

import React from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { Sidebar } from "@/components/Sidebar";
import { useSidebarStore } from "@/store/useSidebarStore";
import { cn } from "@/lib/utils";

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
            "flex-1 transition-[margin] duration-300",
            isCollapsed ? "ml-[100px]" : "ml-[280px]"
          )}
        >
          {children}
        </main>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col">
      <header className="sticky top-0 z-50 w-full glass border-b border-border/40">
        <div className="container mx-auto flex h-20 items-center justify-between px-6">
          <Link href="/" className="group cursor-pointer">
            <Logo />
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
        <footer className="border-t border-border/40 py-24 bg-muted/30">
          <div className="container mx-auto px-6 space-y-16">
            <div className="flex flex-col md:flex-row justify-between items-center gap-12">
              <div className="flex items-center gap-4 opacity-60">
                <Logo size={32} />
              </div>
              <div className="flex gap-12 text-[10px] uppercase tracking-widest font-bold opacity-40">
                <Link href="#" className="hover:opacity-100 transition-opacity">Privacy</Link>
                <Link href="#" className="hover:opacity-100 transition-opacity">Terms</Link>
                <Link href="#" className="hover:opacity-100 transition-opacity">Documentation</Link>
              </div>
              <div className="text-muted-foreground text-[10px] tracking-[0.2em] uppercase font-bold opacity-30">
                © 2026 Architectural Knowledge Systems
              </div>
            </div>
          </div>
        </footer>
    </div>
  );
}
