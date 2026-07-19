"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import React, { useEffect, useState } from "react";

import { Footer } from "@/components/Footer";
import { Logo } from "@/components/Logo";
import { Sidebar } from "@/components/Sidebar";
import { SupportModal } from "@/components/SupportModal";
import { cn } from "@/lib/utils";
import { useSidebarStore } from "@/store/useSidebarStore";

const SCROLL_THRESHOLD = 50;
const APP_ROUTES = ["/dashboard", "/processing", "/upload"];

/**
 * Chooses the chrome for a route: the app shell with a sidebar, or the
 * marketing header and footer.
 */
export function MainLayoutWrapper({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebarStore();
  const pathname = usePathname();

  const [isSupportOpen, setIsSupportOpen] = useState(false);
  const isScrolled = useScrolledPast(SCROLL_THRESHOLD);

  const isLandingPage = pathname === "/";
  const isAppRoute = APP_ROUTES.some((prefix) => pathname?.startsWith(prefix));

  if (isAppRoute) {
    return (
      <div className="flex min-h-screen">
        <Sidebar />
        <main
          className={cn(
            "flex-1 transition-[padding] duration-300 min-h-screen",
            isCollapsed ? "pl-0" : "pl-[280px]",
          )}
        >
          {children}
        </main>
        <SupportModal isOpen={isSupportOpen} onClose={() => setIsSupportOpen(false)} />
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col">
      <header
        className={cn(
          "fixed top-0 z-[100] w-full transition-all duration-500",
          isLandingPage
            ? isScrolled
              ? "bg-cream/95 backdrop-blur-md border-b-2 border-bee-black shadow-[0_4px_0px_0px_#FFB800]"
              : "bg-transparent border-none"
            : "sticky bg-white/80 backdrop-blur-md border-b border-border/40",
        )}
      >
        <div className="container mx-auto flex h-24 items-center justify-between px-8 md:px-12">
          <Link href="/" className="group cursor-pointer">
            <Logo showText={true} />
          </Link>

          <Link
            href="/dashboard"
            className={cn(
              "px-10 py-4 font-black uppercase tracking-[0.2em] text-[10px] transition-all duration-500 shadow-xl",
              isLandingPage
                ? "bg-honey text-bee-black hover:bg-white hover:scale-105"
                : "bg-bee-black text-white hover:bg-honey-500",
            )}
          >
            Open Hive
          </Link>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      {!isLandingPage && <Footer />}

      <SupportModal isOpen={isSupportOpen} onClose={() => setIsSupportOpen(false)} />
    </div>
  );
}

function useScrolledPast(threshold: number): boolean {
  const [isScrolled, setIsScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setIsScrolled(window.scrollY > threshold);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [threshold]);

  return isScrolled;
}
