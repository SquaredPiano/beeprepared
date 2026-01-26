"use client";

import React, { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { Logo } from "@/components/Logo";
import { Sidebar } from "@/components/Sidebar";
import { Footer } from "@/components/Footer";
import { useSidebarStore } from "@/store/useSidebarStore";
import { cn } from "@/lib/utils";
import { HoneyJar } from "@/components/HoneyJar";
import { SupportModal } from "@/components/SupportModal";
import { createClient } from "@/lib/supabase/client";
import { User } from "@supabase/supabase-js";

// Developer mode check - bypasses auth when NEXT_PUBLIC_DEV_MODE=true
const DEV_MODE = process.env.NEXT_PUBLIC_DEV_MODE === "true";

export function MainLayoutWrapper({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebarStore();
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSupportOpen, setIsSupportOpen] = useState(false);
  const [isScrolled, setIsScrolled] = useState(false);
  const supabase = createClient();

  // Route markers
  const isDashboard = pathname?.startsWith("/dashboard");
  const isProcessing = pathname?.startsWith("/processing");
  const isUpload = pathname === "/upload";
  const isAuthPage = pathname?.startsWith("/auth");
  const isLandingPage = pathname === "/";
  const isProtectedRoute = isDashboard || isProcessing || isUpload;
  const isCanvasPage = pathname?.includes("/canvas");

  // Initial session check
  useEffect(() => {
    const checkSession = async () => {
      // In dev mode, skip auth check
      if (DEV_MODE) {
        setIsLoading(false);
        return;
      }
      const { data: { session } } = await supabase.auth.getSession();
      setUser(session?.user ?? null);
      setIsLoading(false);
    };
    checkSession();
  }, [supabase]);

  // Auth state change listener + redirects (skip in dev mode)
  useEffect(() => {
    if (DEV_MODE) return;

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      const currentUser = session?.user ?? null;
      setUser(currentUser);
      setIsLoading(false);

      // Redirect logic
      if (currentUser && (isLandingPage || isAuthPage)) {
        router.replace("/dashboard");
      } else if (!currentUser && isProtectedRoute) {
        router.replace("/auth/login");
      }
    });

    return () => subscription.unsubscribe();
  }, [supabase, pathname, router, isLandingPage, isAuthPage, isProtectedRoute]);

  // Immediate redirect check after loading (skip in dev mode)
  useEffect(() => {
    if (DEV_MODE || isLoading) return;

    if (user && (isLandingPage || isAuthPage)) {
      router.replace("/dashboard");
    } else if (!user && isProtectedRoute) {
      router.replace("/auth/login");
    }
  }, [isLoading, user, isLandingPage, isAuthPage, isProtectedRoute, router]);

  useEffect(() => {
    if (!isLandingPage) return;

    const handleScroll = () => {
      setIsScrolled(window.scrollY > 50);
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, [isLandingPage]);

  const handleAuthAction = async () => {
    if (user) {
      await supabase.auth.signOut();
      router.replace("/");
    } else {
      router.push("/auth/login");
    }
  };

  // Show loading state while checking auth for protected routes (skip in dev mode)
  if (!DEV_MODE && isLoading && isProtectedRoute) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-cream">
        <div className="text-center space-y-4">
          <div className="w-12 h-12 border-4 border-honey border-t-transparent rounded-full animate-spin mx-auto" />
          <p className="text-bee-black/50 font-bold uppercase tracking-widest text-xs">Loading hive...</p>
        </div>
      </div>
    );
  }

  // Block protected routes if not authenticated (skip in dev mode)
  if (!DEV_MODE && !isLoading && !user && isProtectedRoute) {
    return null; // Will redirect via useEffect
  }

  // Block landing/auth if authenticated (skip in dev mode)
  if (!DEV_MODE && !isLoading && user && (isLandingPage || isAuthPage)) {
    return null; // Will redirect via useEffect
  }

  // Persistent Sidebar for all app views (Dashboard, Processing, Upload)
  const showSidebar = isDashboard || isProcessing || isUpload;

  if (showSidebar) {
    return (
      <div className="flex min-h-screen">
        <Sidebar />
        <main
          className={cn(
            "flex-1 transition-[padding] duration-300 min-h-screen",
            isCollapsed ? "pl-0" : "pl-[280px]"
          )}
        >
          {children}
        </main>
        {/* Hide HoneyJar on canvas page */}
        {/* {isDashboard && !isCanvasPage && (
          <HoneyJar points={450} maxPoints={1000} level="Worker Bee" isMystery={true} />
        )} */}
        <SupportModal isOpen={isSupportOpen} onClose={() => setIsSupportOpen(false)} />
      </div>
    );
  }

  // Auth pages don't get the landing header/footer
  if (isAuthPage) {
    return <>{children}</>;
  }

  return (
    <div className="relative flex min-h-screen flex-col">
      <header className={cn(
        "fixed top-0 z-[100] w-full transition-all duration-500",
        isLandingPage
          ? isScrolled
            ? "bg-cream/95 backdrop-blur-md border-b-2 border-bee-black shadow-[0_4px_0px_0px_#FFB800]"
            : "bg-transparent border-none"
          : "sticky bg-white/80 backdrop-blur-md border-b border-border/40"
      )}>
        <div className="container mx-auto flex h-24 items-center justify-between px-8 md:px-12">
          <Link href="/" className="group cursor-pointer">
            <Logo showText={true} />
          </Link>

          <div className="flex items-center gap-8">
            <button
              onClick={handleAuthAction}
              className={cn(
                "px-10 py-4 font-black uppercase tracking-[0.2em] text-[10px] transition-all duration-500 shadow-xl",
                isLandingPage
                  ? "bg-honey text-bee-black hover:bg-white hover:scale-105"
                  : "bg-bee-black text-white hover:bg-honey-500"
              )}
            >
              {user ? "Sign Out" : "Access Hive"}
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1">
        {children}
      </main>

      {/* Only show global footer if NOT the landing page */}
      {!isLandingPage && <Footer />}

      <SupportModal isOpen={isSupportOpen} onClose={() => setIsSupportOpen(false)} />
    </div>
  );
}
