import React from "react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background">
      <div className="flex-1 relative">
        <div className="container mx-auto">
          {children}
        </div>
      </div>
    </div>
  );
}
