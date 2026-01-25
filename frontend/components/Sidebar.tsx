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
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { playSound } from "@/lib/sounds";
import { Logo } from "./Logo";
import { createClient } from "@/lib/supabase/client";

import { useSidebarStore } from "@/store/useSidebarStore";

export function Sidebar() {
  const { isCollapsed, toggle, collapse, expand } = useSidebarStore();
  const pathname = usePathname();
  const router = useRouter();
  const supabase = createClient();

  // Auto-collapse on canvas view
  useEffect(() => {
    if (pathname === "/dashboard/canvas") {
      collapse();
    }
  }, [pathname, collapse]);

  const navItems = [
    { icon: LayoutDashboard, label: "Overview", href: "/dashboard" },
    { icon: Plus, label: "New Task", href: "/upload" },
    { icon: Workflow, label: "Flow Canvas", href: "/dashboard/canvas" },
    { icon: Library, label: "Library", href: "/dashboard/library" },
    { icon: Settings, label: "Settings", href: "/dashboard/settings" },
  ];
  
    return (
      <>
        {/* Expand Trigger - Floating button when sidebar is fully collapsed */}
        <AnimatePresence>
          {isCollapsed && (
            <motion.button
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              onClick={expand}
              onMouseEnter={() => playSound("hover")}
              className="fixed left-6 top-8 z-[60] w-12 h-12 bg-bee-black border border-white/10 rounded-2xl flex items-center justify-center hover:bg-honey-500 hover:text-bee-black transition-all shadow-2xl cursor-pointer text-white"
            >
              <ChevronRight size={20} />
            </motion.button>
          )}
        </AnimatePresence>

        <motion.aside
          initial={false}
          animate={{ 
            width: isCollapsed ? 0 : 280,
            x: isCollapsed ? -280 : 0
          }}
          transition={{ type: "spring", damping: 25, stiffness: 200 }}
          className="fixed left-0 top-0 h-screen bg-[#0F0F0F] text-white border-r border-white/5 z-50 flex flex-col overflow-hidden shadow-[20px_0_60px_-15px_rgba(0,0,0,0.5)]"
        >
          {/* Logo Section */}
          <div className="flex items-center justify-between p-8 border-b border-white/5 h-24 shrink-0">
            <Link 
              href="/" 
              className="cursor-pointer group flex items-center gap-3 min-w-0"
              onMouseEnter={() => playSound("hover")}
            >
              <Logo size={24} showText={false} className="group-hover:scale-110 transition-transform shrink-0" />
              <div className="overflow-hidden">
                <span className="font-display font-bold text-xs uppercase tracking-[0.2em] whitespace-nowrap group-hover:text-honey-500 transition-colors">
                  BeePrepared
                </span>
              </div>
            </Link>
            
            <button
              onClick={(e) => {
                e.stopPropagation();
                collapse();
                playSound("drop");
              }}
              onMouseEnter={() => playSound("hover")}
              className="p-2 hover:bg-white/10 rounded-lg transition-all cursor-pointer"
            >
              <ChevronLeft size={16} />
            </button>
          </div>

          {/* Navigation */}
          <nav className="p-6 space-y-2 flex-1">
            <div className="text-[10px] uppercase tracking-[0.3em] font-bold opacity-30 px-4 mb-6">Navigation</div>
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              
                return (
                  <Link key={item.href} href={item.href} className="block cursor-pointer">
                    <motion.div
                      whileHover={{ x: 4 }}
                      onMouseEnter={() => playSound("hover")}
                      onClick={() => playSound("pickup")}
                      className={cn(
                        "flex items-center gap-4 px-4 py-4 rounded-2xl transition-all relative group",
                        isActive 
                          ? "bg-honey-500 text-bee-black shadow-lg shadow-honey-500/20" 
                          : "hover:bg-white/5"
                      )}
                    >
                    <Icon size={18} className={cn(
                      "shrink-0",
                      isActive ? "text-bee-black" : "opacity-40 group-hover:opacity-100"
                    )} />
                    <span className="text-[10px] uppercase tracking-[0.2em] font-bold whitespace-nowrap">
                      {item.label}
                    </span>
                    
                    {isActive && (
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
          <div className="p-6 border-t border-white/5 space-y-4 shrink-0">
            <a 
              href="mailto:support@beeprepared.ai"
              onMouseEnter={() => playSound("hover")}
              className="w-full px-4 py-3 text-white/40 hover:text-white hover:bg-white/5 rounded-xl transition-all flex items-center gap-4 group cursor-pointer"
            >
              <HelpCircle size={18} className="shrink-0" />
              <span className="text-[10px] uppercase tracking-widest font-bold">Support</span>
            </a>
            <button 
              onMouseEnter={() => playSound("hover")}
              onClick={async () => {
                playSound("pickup");
                await supabase.auth.signOut();
                router.replace("/");
              }}
              className="w-full px-4 py-3 text-red-400/60 hover:text-red-400 hover:bg-red-400/5 rounded-xl transition-all flex items-center gap-4 group cursor-pointer"
            >
              <LogOut size={18} className="shrink-0" />
              <span className="text-[10px] uppercase tracking-widest font-bold">Log Out</span>
            </button>
          </div>
        </motion.aside>
      </>
    );
  }
