"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { BeeMascot } from "@/components/ui/BeeMascot";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const isCanvasPage = pathname?.includes("/canvas");

  return (
    <div className="relative w-full">
      {children}
      {/* Hide mascot on canvas to reduce distraction */}
      {!isCanvasPage && <BeeMascot />}
    </div>
  );
}
