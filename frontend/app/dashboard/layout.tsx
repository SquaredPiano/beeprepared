"use client";

import React, { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { BeeMascot } from "@/components/ui/BeeMascot";
import { isAuthenticated } from "@/lib/auth";
import { Loader2, Hexagon } from "lucide-react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const isCanvasPage = pathname?.includes("/canvas");

  const [authChecked, setAuthChecked] = useState(false);
  const [isAuthed, setIsAuthed] = useState(false);

  useEffect(() => {
    const checkAuth = async () => {
      const authed = await isAuthenticated();
      setIsAuthed(authed);
      setAuthChecked(true);

      if (!authed) {
        router.replace("/auth/login");
      }
    };
    checkAuth();
  }, [router]);

  // Show loading while checking auth
  if (!authChecked) {
    return (
      <div className="min-h-screen bg-cream flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="p-4 bg-honey rounded-2xl animate-pulse">
            <Hexagon className="w-8 h-8 text-bee-black" />
          </div>
          <div className="flex items-center gap-2 text-bee-black/50">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-xs font-bold uppercase tracking-widest">Authenticating...</span>
          </div>
        </div>
      </div>
    );
  }

  // Don't render content if not authenticated (redirect is in progress)
  if (!isAuthed) {
    return null;
  }

  return (
    <div className="relative w-full">
      {children}
      {/* Hide mascot on canvas to reduce distraction */}
      {!isCanvasPage && <BeeMascot />}
    </div>
  );
}
