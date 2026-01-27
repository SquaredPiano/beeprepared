"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { 
  LayoutDashboard, 
  Library, 
  Settings, 
  GitBranch, 
  PlusCircle,
  HelpCircle,
  LogOut,
  ChevronRight
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Logo } from "./Logo";

const menuItems = [
  { icon: LayoutDashboard, label: "Overview", href: "/dashboard" },
  { icon: PlusCircle, label: "New Task", href: "/upload" },
  { icon: GitBranch, label: "Flow Canvas", href: "/dashboard/canvas" },
  { icon: Library, label: "Library", href: "/dashboard/library" },
  { icon: Settings, label: "Settings", href: "/dashboard/settings" },
];

export function DashboardSidebar() {
  const pathname = usePathname();

  return (
    <div className="w-72 h-screen border-r border-border/40 flex flex-col glass fixed left-0 top-0 z-50">
      <div className="p-10 border-b border-border/40">
        <Link href="/" className="group cursor-pointer">
          <Logo />
        </Link>
      </div>

      <nav className="flex-1 px-6 py-10 space-y-2">
        <div className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-30 px-4 mb-6">Navigation</div>
        {menuItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "group flex items-center justify-between px-4 py-4 rounded-2xl transition-all duration-500 cursor-pointer",
                isActive 
                  ? "bg-bee-black text-white shadow-lg shadow-bee-black/10" 
                  : "hover:bg-honey-50/50 hover:translate-x-1"
              )}
            >
              <div className="flex items-center gap-4">
                <item.icon className={cn(
                  "w-5 h-5 transition-colors",
                  isActive ? "text-honey-400" : "opacity-40 group-hover:opacity-100"
                )} />
                <span className={cn(
                  "text-xs uppercase tracking-widest font-bold",
                  isActive ? "text-white" : "opacity-60 group-hover:opacity-100"
                )}>
                  {item.label}
                </span>
              </div>
              {isActive && <div className="w-1.5 h-1.5 rounded-full bg-honey-400" />}
            </Link>
          );
        })}
      </nav>

      <div className="p-8 border-t border-border/40 space-y-4">
        <button className="flex items-center gap-4 px-4 py-3 rounded-xl w-full hover:bg-honey-50/50 transition-all cursor-pointer group">
          <HelpCircle className="w-4 h-4 opacity-40 group-hover:opacity-100" />
          <span className="text-[10px] uppercase tracking-widest font-bold opacity-60 group-hover:opacity-100">Support</span>
        </button>
        <button className="flex items-center gap-4 px-4 py-3 rounded-xl w-full hover:bg-red-50 text-red-600/60 hover:text-red-600 transition-all cursor-pointer group">
          <LogOut className="w-4 h-4" />
          <span className="text-[10px] uppercase tracking-widest font-bold">Log Out</span>
        </button>
      </div>
    </div>
  );
}
