import React from "react";
import Image from "next/image";
import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  size?: number;
  showText?: boolean;
}

export function Logo({ className, size = 40, showText = true }: LogoProps) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div 
        className="relative flex items-center justify-center transition-transform duration-500 hover:rotate-12"
        style={{ width: size, height: size }}
      >
        <Image
          src="/logo.png"
          alt="BeePrepared Logo"
          width={size}
          height={size}
          className="object-contain"
          priority
        />
      </div>
      {showText && (
        <span className="font-display text-xl tracking-tighter uppercase font-bold text-bee-black">
          BeePrepared
        </span>
      )}
    </div>
  );
}
