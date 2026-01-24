import React from "react";
import { BeeMascot } from "@/components/ui/BeeMascot";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative w-full">
      {children}
      <BeeMascot />
    </div>
  );
}
