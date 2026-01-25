"use client";

import React, { useCallback, useState } from "react";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, File, CheckCircle2 } from "lucide-react";
import { useStore } from "@/store/useStore";
import { useIngestionStore } from "@/store/ingestionStore";
import { cn } from "@/lib/utils";
import { toast } from "sonner";


export function HoneyDropZone() {
  const { addFile, files } = useStore();
  const { addTask } = useIngestionStore();

  const onDrop = useCallback((acceptedFiles: File[]) => {
    acceptedFiles.forEach((file) => {
      // Check for 1GB limit (mock check for now using state)
      const currentStorage = useStore.getState().getTotalUsedStorage();
      if (currentStorage + file.size > 1 * 1024 * 1024 * 1024) {
        toast.error(`Storage limit exceeded! Cannot add ${file.name}`);
        return;
      }

      const id = addFile(file.name, file.size);
      addTask({
        id,
        name: file.name,
        status: 'pending',
        progress: 0,
        type: file.type.includes('pdf') ? 'pdf' : file.type.includes('audio') ? 'audio' : 'video',
        timestamp: Date.now()
      });
    });
  }, [addFile, addTask]);


  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "audio/*": [".mp3", ".wav", ".m4a"],
      "video/*": [".mp4", ".mov"],
    },
  });

  return (
    <div className="w-full max-w-2xl mx-auto space-y-6">
      <div
        {...getRootProps()}
        className={cn(
          "relative group cursor-pointer overflow-hidden transition-all duration-500",
          "aspect-[16/9] flex flex-col items-center justify-center rounded-2xl border-2 border-dashed",
          isDragActive 
            ? "border-honey-500 bg-honey-50/50 scale-[0.99]" 
            : "border-border hover:border-honey-300 hover:bg-honey-50/10"
        )}
      >
        <input {...getInputProps()} />
        
        <AnimatePresence mode="wait">
          {isDragActive ? (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex flex-col items-center gap-4"
            >
              <div className="w-16 h-16 bg-honey-500 rounded-full flex items-center justify-center animate-bounce">
                <Upload className="text-white w-8 h-8" />
              </div>
              <p className="text-honey-700 font-display text-lg uppercase tracking-wider font-bold">Drop to Upload</p>
            </motion.div>
          ) : (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex flex-col items-center gap-4"
            >
              <div className="w-16 h-16 border border-border group-hover:border-honey-400 rounded-full flex items-center justify-center transition-colors">
                <Upload className="text-muted-foreground group-hover:text-honey-500 w-6 h-6 transition-colors" />
              </div>
              <div className="text-center space-y-1">
                <p className="font-display text-lg uppercase tracking-wider font-bold cursor-pointer">Add Files</p>

                <p className="text-muted-foreground text-[10px] uppercase tracking-widest font-bold opacity-40">PDF, Audio, or Video</p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Decorative accents */}
        <div className="absolute top-4 right-4 opacity-10 group-hover:opacity-20 transition-opacity">
          <div className="w-8 h-8 border-t-2 border-r-2 border-honey-500 rounded-tr-lg" />
        </div>
        <div className="absolute bottom-4 left-4 opacity-10 group-hover:opacity-20 transition-opacity">
          <div className="w-8 h-8 border-b-2 border-l-2 border-honey-500 rounded-bl-lg" />
        </div>
      </div>

      <div className="space-y-3">
        {files.map((file) => (
          <motion.div
            key={file.id}
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-center justify-between p-4 glass rounded-xl border border-border/40"
          >
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-muted rounded-lg flex items-center justify-center">
                <File className="text-muted-foreground w-5 h-5" />
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-tight">{file.name}</p>
                <p className="text-[10px] uppercase tracking-widest font-bold opacity-40">{file.status}</p>
              </div>
            </div>
            {file.status === "completed" ? (
              <CheckCircle2 className="text-green-500 w-5 h-5" />
            ) : (
              <div className="w-20 bg-muted h-1 rounded-full overflow-hidden">
                <motion.div 
                  className="bg-honey-500 h-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${file.progress}%` }}
                />
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </div>
  );
}
