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

export function MainLayoutWrapper({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebarStore();
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [isSupportOpen, setIsSupportOpen] = useState(false);
  const supabase = createClient();

  const isDashboard = pathname?.startsWith("/dashboard");
  const isProcessing = pathname?.startsWith("/processing");
  const isUpload = pathname === "/upload";
  const isAuthPage = pathname?.startsWith("/auth");

    useEffect(() => {
      const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
        const currentUser = session?.user ?? null;
        setUser(currentUser);
        
        // Redirect logic based on pathname
        if (currentUser && pathname === "/") {
          router.push("/dashboard");
        } else if (!currentUser && (pathname?.startsWith("/dashboard") || pathname?.startsWith("/processing") || pathname === "/upload")) {
          router.push("/auth/login");
        }
      });

      return () => subscription.unsubscribe();
    }, [supabase, pathname, router]);

    const handleAuthAction = async () => {
      if (user) {
        await supabase.auth.signOut();
        router.push("/");
      } else {
        router.push("/auth/login");
      }
    };

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
          {isDashboard && (
            <HoneyJar points={450} maxPoints={1000} level="Worker Bee" isMystery={true} />
          )}
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
        <header className="sticky top-0 z-50 w-full glass border-b border-border/40">
          <div className="container mx-auto flex h-20 items-center justify-between px-6 md:px-12 lg:px-24">
            <Link href="/" className="group cursor-pointer">
              <Logo showText={true} />
            </Link>
            
            <div className="flex items-center gap-8">
              <button 
                onClick={handleAuthAction}
                className="bg-bee-black text-white px-10 py-3.5 rounded-full hover:bg-honey-500 transition-all duration-500 font-display text-[10px] font-bold uppercase tracking-[0.2em] cursor-pointer shadow-xl shadow-bee-black/10"
              >
                {user ? "Sign Out" : "Access Hive"}
              </button>
            </div>
          </div>
        </header>

      <main className="flex-1">
        {children}
      </main>
      <Footer />
      <SupportModal isOpen={isSupportOpen} onClose={() => setIsSupportOpen(false)} />
    </div>
  );
}
