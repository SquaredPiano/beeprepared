"use client";

import { motion } from 'framer-motion';
import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface FeatureCardProps {
  icon: ReactNode | string;
  title: string;
  description: string;
  featured?: boolean;
}

export function FeatureCard({ icon, title, description, featured = false }: FeatureCardProps) {
  return (
    <motion.div
      whileHover={{ y: -6 }}
      className={cn(
        "relative h-full rounded-2xl p-8 border transition-all duration-200",
        featured
          ? "bg-honey/10 border-honey/30 shadow-sm"
          : "bg-white border-wax shadow-sm hover:shadow-md"
      )}
    >
      <div className="flex items-start gap-6">
        {/* Icon */}
        <div
          className={cn(
            "flex items-center justify-center w-14 h-14 rounded-full shrink-0",
            featured ? "bg-honey/20 border border-honey/40" : "bg-bee-black/5 border border-bee-black/10"
          )}
        >
          <div className="text-2xl">{icon}</div>
        </div>

        {/* Content */}
        <div className="flex-1">
          <h3 className="text-xl font-display uppercase tracking-tight text-bee-black">
            {title}
          </h3>
          <p className="mt-3 text-sm leading-relaxed text-bee-black/60">
            {description}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
