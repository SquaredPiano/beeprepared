"use client";

import React from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Trash2, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

interface DeleteConfirmationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  title: string;
  description: string;
  itemName?: string;
  destructive?: boolean;
}

export function DeleteConfirmationDialog({
  open,
  onOpenChange,
  onConfirm,
  title,
  description,
  itemName,
  destructive = true,
}: DeleteConfirmationDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="rounded-[32px] border-wax bg-cream/95 backdrop-blur-xl max-w-md">
        <AlertDialogHeader>
          <div className="flex items-center gap-4 mb-2">
            <div className={cn(
              "w-12 h-12 rounded-2xl flex items-center justify-center shadow-inner",
              destructive ? "bg-red-50 text-red-600" : "bg-honey/10 text-honey-600"
            )}>
              {destructive ? (
                <Trash2 className="h-6 w-6" />
              ) : (
                <AlertTriangle className="h-6 w-6" />
              )}
            </div>
            <AlertDialogTitle className="text-xl font-display uppercase tracking-tight text-bee-black">
              {title}
            </AlertDialogTitle>
          </div>
          <AlertDialogDescription className="text-sm text-bee-black/60 leading-relaxed">
            {description}
            {itemName && (
              <span className="block mt-3 p-3 rounded-xl bg-bee-black/5 font-bold text-bee-black border border-bee-black/5">
                "{itemName}"
              </span>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="mt-8 gap-3">
          <AlertDialogCancel className="rounded-xl border-wax bg-transparent hover:bg-bee-black/5 text-bee-black/60 font-bold uppercase text-[10px] tracking-widest h-12 px-6">
            Cancel
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.stopPropagation();
              onConfirm();
            }}
            className={cn(
              "rounded-xl font-bold uppercase text-[10px] tracking-widest h-12 px-8 shadow-lg transition-all",
              destructive 
                ? "bg-red-600 text-white hover:bg-red-700 shadow-red-600/20"
                : "bg-honey text-bee-black hover:bg-honey-600 shadow-honey/20"
            )}
          >
            {destructive ? "Delete" : "Confirm"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
