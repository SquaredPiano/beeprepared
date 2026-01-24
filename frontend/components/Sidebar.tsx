"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { 
  LayoutDashboard, 
  Plus, 
  Workflow, 
  Library, 
  Settings,
  ChevronLeft,
  ChevronRight,
  HelpCircle,
  LogOut
} from "lucide-react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";
import { Logo } from "./Logo";

export function Sidebar() {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const pathname = usePathname();
  
  const navItems = [
    { icon: LayoutDashboard, label: "Overview", href: "/dashboard" },
    { icon: Plus, label: "New Task", href: "/upload" },
    { icon: Workflow, label: "Flow Canvas", href: "/dashboard/canvas" },
    { icon: Library, label: "Library", href: "/dashboard/library" },
    { icon: Settings, label: "Settings", href: "/dashboard/settings" },
  ];
  
  return (
    <motion.aside
      initial={false}
      animate={{ width: isCollapsed ? 100 : 280 }}
      className="fixed left-0 top-0 h-screen bg-bee-black text-white border-r border-white/5 z-50 flex flex-col"
    >
      {/* Logo Section */}
      <div className="flex items-center justify-between p-8 border-b border-white/5 h-24">
        <AnimatePresence mode="wait">
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              className="flex items-center gap-2"
            >
              <Logo size={24} />
              <span className="font-display font-bold text-xs uppercase tracking-[0.2em] whitespace-nowrap">BeePrepared</span>
            </motion.div>
          )}
          {isCollapsed && (
             <motion.div
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.8 }}
              className="flex items-center justify-center w-full"
            >
              <Logo size={24} />
            </motion.div>
          )}
        </AnimatePresence>
        
        {!isCollapsed && (
          <button
            onClick={() => {
              setIsCollapsed(!isCollapsed);
              playSound("pickup");
            }}
            onMouseEnter={() => playSound("hover")}
            className="p-2 hover:bg-white/10 rounded-lg transition-colors cursor-pointer"
          >
            <ChevronLeft size={16} />
          </button>
        )}
      </div>

      {isCollapsed && (
        <button
          onClick={() => {
            setIsCollapsed(!isCollapsed);
            playSound("drop");
          }}
          onMouseEnter={() => playSound("hover")}
          className="mx-auto mt-4 p-2 hover:bg-white/10 rounded-lg transition-colors cursor-pointer"
        >
          <ChevronRight size={16} />
        </button>
      )}
      
      {/* Navigation */}
      <nav className="p-6 space-y-2 flex-1">
        {!isCollapsed && (
           <div className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-30 px-4 mb-6">Navigation</div>
        )}
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;
          
          return (
            <Link key={item.href} href={item.href} className="block">
              <motion.div
                whileHover={{ x: isCollapsed ? 0 : 4 }}
                onMouseEnter={() => playSound("hover")}
                onClick={() => playSound("pickup")}
                className={cn(
                  "flex items-center gap-4 px-4 py-4 rounded-2xl transition-all cursor-pointer relative group",
                  isActive 
                    ? "bg-honey-500 text-bee-black shadow-lg shadow-honey-500/20" 
                    : "hover:bg-white/5"
                )}
              >
                <Icon size={18} className={cn(
                  "shrink-0",
                  isActive ? "text-bee-black" : "opacity-40 group-hover:opacity-100"
                )} />
                <AnimatePresence mode="wait">
                  {!isCollapsed && (
                    <motion.span
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      exit={{ opacity: 0, x: -10 }}
                      className="text-[10px] uppercase tracking-[0.2em] font-bold whitespace-nowrap"
                    >
                      {item.label}
                    </motion.span>
                  )}
                </AnimatePresence>
                
                {isActive && !isCollapsed && (
                  <motion.div
                    layoutId="activeIndicator"
                    className="absolute right-4 w-1.5 h-1.5 bg-bee-black rounded-full"
                  />
                )}
              </motion.div>
            </Link>
          );
        })}
      </nav>
      
      {/* Footer Actions */}
      <div className="p-6 border-t border-white/5 space-y-4">
        <button 
          onMouseEnter={() => playSound("hover")}
          className="w-full px-4 py-3 text-white/40 hover:text-white hover:bg-white/5 rounded-xl transition-all flex items-center gap-4 group cursor-pointer"
        >
          <HelpCircle size={18} className="shrink-0" />
          {!isCollapsed && <span className="text-[10px] uppercase tracking-widest font-bold">Support</span>}
        </button>
        <button 
          onMouseEnter={() => playSound("hover")}
          className="w-full px-4 py-3 text-red-400/60 hover:text-red-400 hover:bg-red-400/5 rounded-xl transition-all flex items-center gap-4 group cursor-pointer"
        >
          <LogOut size={18} className="shrink-0" />
          {!isCollapsed && <span className="text-[10px] uppercase tracking-widest font-bold">Log Out</span>}
        </button>
      </div>
    </motion.aside>
  );
}
