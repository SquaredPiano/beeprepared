"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "framer-motion";
import { 
  X, 
  Upload, 
  FileText, 
  Video, 
  Presentation, 
  Loader2, 
  Check
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useCanvasStore } from "@/store/useCanvasStore";

interface AssetUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUpload?: (asset: { label: string; type: "pdf" | "video" | "pptx"; id: string }) => void;
}

export function AssetUploadModal({ isOpen, onClose, onUpload }: AssetUploadModalProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string>("Uploading...");
  const [activeTab, setActiveTab] = useState("upload");
  const { currentProjectId, uploadFile, refreshArtifacts } = useCanvasStore();

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;

    const file = acceptedFiles[0];
    
    if (!currentProjectId) {
      toast.error("Please save your project first");
      return;
    }

    setIsUploading(true);
    setUploadProgress("Uploading file...");
    
    try {
      // Use the canvas store's uploadFile which handles the full pipeline
      setUploadProgress("Processing...");
      
      await api.upload.uploadAndIngest(
        currentProjectId,
        file,
        (job) => {
          if (job.status === "running") {
            setUploadProgress("Extracting knowledge...");
          }
        }
      );
      
      // Refresh the canvas to show new artifacts
      await refreshArtifacts();
      
      toast.success(`${file.name} processed successfully`);
      
      // Optional callback for legacy compatibility
      if (onUpload) {
        const type = file.type.includes('pdf') ? 'pdf' : 
                     file.type.includes('video') ? 'video' : 
                     file.type.includes('presentation') || file.name.endsWith('pptx') ? 'pptx' : 'pdf';
        onUpload({
          label: file.name,
          type: type as 'pdf' | 'video' | 'pptx',
          id: 'processed'
        });
      }
      
      onClose();
    } catch (error: any) {
      console.error("Upload error:", error);
      toast.error(error.message || "Upload failed");
    } finally {
      setIsUploading(false);
      setUploadProgress("Uploading...");
    }
  }, [currentProjectId, refreshArtifacts, onUpload, onClose]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "video/*": [".mp4", ".mov", ".avi"],
      "audio/*": [".mp3", ".wav", ".m4a"],
      "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
      "text/markdown": [".md"],
      "text/plain": [".txt"]
    },
    multiple: false
  });

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6 md:p-8">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-bee-black/60 backdrop-blur-md"
          />
          
          <motion.div
            initial={{ scale: 0.95, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 20 }}
            className="relative w-full max-w-2xl bg-cream rounded-[2.5rem] shadow-2xl border border-wax overflow-hidden flex flex-col max-h-[85vh]"
          >
            {/* Header */}
            <div className="p-8 border-b border-wax flex justify-between items-center bg-white/50 backdrop-blur-xl shrink-0">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-honey/10 rounded-2xl">
                  <Upload className="w-6 h-6 text-honey" />
                </div>
                <div>
                  <h2 className="text-2xl font-serif font-bold text-bee-black">Upload Source</h2>
                  <p className="text-[10px] uppercase tracking-widest font-bold text-bee-black/40">Add content to your project</p>
                </div>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-wax/50 rounded-full transition-colors cursor-pointer group">
                <X className="w-6 h-6 text-bee-black/20 group-hover:text-bee-black transition-colors" />
              </button>
            </div>

            <div className="p-8 flex flex-col gap-8 overflow-y-auto">
              <div
                {...getRootProps()}
                className={`
                  relative border-2 border-dashed rounded-[2rem] p-16 transition-all duration-500 flex flex-col items-center gap-6 cursor-pointer group
                  ${isDragActive ? 'border-honey bg-honey/5' : 'border-wax hover:border-honey/40 hover:bg-honey/5'}
                  ${isUploading ? 'pointer-events-none opacity-50' : ''}
                `}
              >
                <input {...getInputProps()} />
                
                <div className={`p-6 rounded-3xl bg-white shadow-xl text-honey transition-all duration-700 ${isDragActive ? 'scale-110 rotate-12 shadow-honey/20' : 'group-hover:scale-105'}`}>
                  {isUploading ? (
                    <Loader2 className="w-10 h-10 animate-spin" />
                  ) : (
                    <Upload className="w-10 h-10" />
                  )}
                </div>

                <div className="text-center space-y-2">
                  <p className="text-xl font-bold text-bee-black">
                    {isUploading ? uploadProgress : 'Drop your file here'}
                  </p>
                  <p className="text-xs text-bee-black/40 font-medium uppercase tracking-widest">
                    PDF • MP4 • MP3 • PPTX • TXT • MD
                  </p>
                </div>

                {!isUploading && (
                  <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-bee-black/5 text-[9px] font-bold uppercase tracking-[0.2em] text-bee-black/40">
                    <Check size={10} className="text-green-500" /> Ready to process
                  </div>
                )}

                {isDragActive && (
                  <motion.div 
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="absolute inset-0 bg-honey/10 rounded-[2rem] pointer-events-none border-2 border-honey"
                  />
                )}
              </div>

              <div className="grid grid-cols-3 gap-4">
                {[
                  { icon: FileText, label: 'Documents', sub: 'PDF, TXT, MD', color: 'bg-blue-50 text-blue-500' },
                  { icon: Video, label: 'Media', sub: 'MP4, MP3, WAV', color: 'bg-purple-50 text-purple-500' },
                  { icon: Presentation, label: 'Slides', sub: 'PPTX', color: 'bg-orange-50 text-orange-500' }
                ].map((item, i) => (
                  <div key={i} className="p-6 rounded-3xl bg-white border border-wax hover:border-honey/20 transition-all duration-500 group">
                    <div className={`w-10 h-10 rounded-xl flex items-center justify-center mb-4 transition-transform group-hover:scale-110 ${item.color}`}>
                      <item.icon className="w-5 h-5" />
                    </div>
                    <p className="text-[10px] font-bold text-bee-black uppercase tracking-widest mb-1">{item.label}</p>
                    <p className="text-[9px] font-bold text-bee-black/30 uppercase tracking-widest">{item.sub}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Footer */}
            <div className="p-8 border-t border-wax bg-cream/50 flex justify-end items-center shrink-0">
              <Button variant="ghost" onClick={onClose} className="rounded-xl font-bold uppercase text-[10px] tracking-widest px-6 h-12">
                Cancel
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
