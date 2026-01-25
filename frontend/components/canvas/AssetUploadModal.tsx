"use client";

import { useState, useCallback, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";

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
  const [activeTab, setActiveTab] = useState<"upload" | "library">("upload");
  const [existingArtifacts, setExistingArtifacts] = useState<any[]>([]);
  const { currentProjectId, uploadFile, refreshArtifacts, setNodes, nodes, takeSnapshot } = useCanvasStore();

  useEffect(() => {
    if (isOpen && currentProjectId && activeTab === "library") {
      loadExistingArtifacts();
    }
  }, [isOpen, currentProjectId, activeTab]);

  const loadExistingArtifacts = async () => {
    try {
      const { artifacts } = await api.projects.getArtifacts(currentProjectId!);
      setExistingArtifacts(artifacts);
    } catch (error) {
      console.error("Failed to load artifacts:", error);
    }
  };

  const selectExistingArtifact = (artifact: any) => {
    // Convert artifact to node and add to canvas
    const newNode = {
      id: artifact.id,
      type: "artifactNode",
      position: { x: 100, y: 100 },
      data: {
        label: artifact.type.toUpperCase(),
        type: artifact.type,
        artifact: artifact,
        status: "completed"
      }
    };
    
    setNodes([...nodes, newNode as any]);
    takeSnapshot();
    onClose();
    toast.success("Artifact added to canvas");
  };


  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;

    const file = acceptedFiles[0];
    
    let projectId = currentProjectId;
    
    if (!projectId) {
      setUploadProgress("Initializing project...");
      try {
        await useCanvasStore.getState().save();
        projectId = useCanvasStore.getState().currentProjectId;
        if (!projectId) throw new Error("Failed to initialize project");
      } catch (err: any) {
        toast.error("Could not initialize project for upload");
        setIsUploading(false);
        return;
      }
    }

    setIsUploading(true);
    setUploadProgress("Uploading file...");
    
    try {
      // Use the canvas store's uploadFile which handles the full pipeline
      setUploadProgress("Processing...");
      
      await api.upload.uploadAndIngest(
        projectId,
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
              <div className="flex items-center gap-6">
                <div className="p-3 bg-honey/10 rounded-2xl">
                  <Upload className="w-6 h-6 text-honey" />
                </div>
                <div className="flex flex-col">
                  <div className="flex items-center gap-4">
                    <button 
                      onClick={() => setActiveTab("upload")}
                      className={cn(
                        "text-xl font-serif font-bold transition-all",
                        activeTab === "upload" ? "text-bee-black" : "text-bee-black/20 hover:text-bee-black/40"
                      )}
                    >
                      Upload New
                    </button>
                    <div className="w-px h-4 bg-wax" />
                    <button 
                      onClick={() => setActiveTab("library")}
                      className={cn(
                        "text-xl font-serif font-bold transition-all",
                        activeTab === "library" ? "text-bee-black" : "text-bee-black/20 hover:text-bee-black/40"
                      )}
                    >
                      Library
                    </button>
                  </div>
                  <p className="text-[10px] uppercase tracking-widest font-bold text-bee-black/40">
                    {activeTab === "upload" ? "Add fresh content to your hive" : "Bring existing assets to canvas"}
                  </p>
                </div>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-wax/50 rounded-full transition-colors cursor-pointer group">
                <X className="w-6 h-6 text-bee-black/20 group-hover:text-bee-black transition-colors" />
              </button>
            </div>


            <div className="p-8 flex flex-col gap-8 overflow-y-auto min-h-[400px]">
              {activeTab === "upload" ? (
                <>
                  <div
                    {...getRootProps()}
                    className={cn(
                      "relative border-2 border-dashed rounded-[2rem] p-16 transition-all duration-500 flex flex-col items-center gap-6 cursor-pointer group",
                      isDragActive ? 'border-honey bg-honey/5' : 'border-wax hover:border-honey/40 hover:bg-honey/5',
                      isUploading && 'pointer-events-none opacity-50'
                    )}
                  >
                    <input {...getInputProps()} />
                    
                    <div className={cn(
                      "p-6 rounded-3xl bg-white shadow-xl text-honey transition-all duration-700",
                      isDragActive ? 'scale-110 rotate-12 shadow-honey/20' : 'group-hover:scale-105'
                    )}>
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
                  </div>

                  <div className="grid grid-cols-3 gap-4">
                    {[
                      { icon: FileText, label: 'Documents', sub: 'PDF, TXT, MD', color: 'bg-blue-50 text-blue-500' },
                      { icon: Video, label: 'Media', sub: 'MP4, MP3, WAV', color: 'bg-purple-50 text-purple-500' },
                      { icon: Presentation, label: 'Slides', sub: 'PPTX', color: 'bg-orange-50 text-orange-500' }
                    ].map((item, i) => (
                      <div key={i} className="p-6 rounded-3xl bg-white border border-wax hover:border-honey/20 transition-all duration-500 group">
                        <div className={cn(
                          "w-10 h-10 rounded-xl flex items-center justify-center mb-4 transition-transform group-hover:scale-110",
                          item.color
                        )}>
                          <item.icon className="w-5 h-5" />
                        </div>
                        <p className="text-[10px] font-bold text-bee-black uppercase tracking-widest mb-1">{item.label}</p>
                        <p className="text-[9px] font-bold text-bee-black/30 uppercase tracking-widest">{item.sub}</p>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="space-y-4">
                  {existingArtifacts.length > 0 ? (
                    <div className="grid grid-cols-1 gap-3">
                      {existingArtifacts.map((artifact) => (
                        <button
                          key={artifact.id}
                          onClick={() => selectExistingArtifact(artifact)}
                          className="flex items-center justify-between p-4 rounded-2xl bg-white border border-wax hover:border-honey/40 hover:bg-honey/5 transition-all group group cursor-pointer"
                        >
                          <div className="flex items-center gap-4">
                            <div className="w-10 h-10 rounded-xl bg-wax/20 flex items-center justify-center text-bee-black/40 group-hover:bg-honey/10 group-hover:text-honey transition-colors">
                              {artifact.type === 'video' ? <Video size={18} /> : <FileText size={18} />}
                            </div>
                            <div className="text-left">
                              <p className="text-sm font-bold text-bee-black truncate max-w-[300px]">{artifact.content?.title || 'Unnamed Asset'}</p>
                              <p className="text-[9px] uppercase tracking-widest font-bold opacity-30">{artifact.type}</p>
                            </div>
                          </div>
                          <div className="px-3 py-1 rounded-full bg-wax/10 text-[8px] font-bold uppercase tracking-widest opacity-0 group-hover:opacity-100 transition-opacity">
                            Add to Canvas
                          </div>
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="py-20 text-center space-y-4 border-2 border-dashed border-wax rounded-[2rem]">
                      <div className="w-16 h-16 bg-wax/20 rounded-full flex items-center justify-center mx-auto opacity-20">
                        <FileText size={32} />
                      </div>
                      <p className="text-xs font-bold uppercase tracking-widest opacity-30">No artifacts found in this hive yet.</p>
                    </div>
                  )}
                </div>
              )}
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
