import React from "react";
import { DashboardSidebar } from "@/components/DashboardSidebar";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <DashboardSidebar />
      <div className="flex-1 ml-72 relative">
        <div className="container mx-auto">
          {children}
        </div>
      </div>
    </div>
  );
}
