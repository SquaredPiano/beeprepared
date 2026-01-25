"use client";

import { useState, useCallback, useEffect } from "react";
import { useDropzone } from "react-dropzone";
import { motion, AnimatePresence } from "framer-motion";
import { 
  X, 
  Upload, 
  FileText, 
  Video, 
  Presentation, 
  Loader2, 
  Database, 
  Check, 
  Plus,
  ArrowRight,
  Search,
  Trash2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";
import { api, Asset } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";

interface AssetUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onUpload: (asset: { label: string; type: "pdf" | "video" | "pptx"; id: string }) => void;
}

export function AssetUploadModal({ isOpen, onClose, onUpload }: AssetUploadModalProps) {
  const [isUploading, setIsUploading] = useState(false);
  const [activeTab, setActiveTab] = useState("upload");
  const [existingAssets, setExistingAssets] = useState<Asset[]>([]);
  const [isLoadingAssets, setIsLoadingAssets] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchAssets = useCallback(async () => {
    setIsLoadingAssets(true);
    try {
      const assets = await api.assets.list();
      setExistingAssets(assets);
    } catch (error) {
      console.error("Failed to fetch assets:", error);
    } finally {
      setIsLoadingAssets(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen && activeTab === "workspace") {
      fetchAssets();
    }
  }, [isOpen, activeTab, fetchAssets]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;

    setIsUploading(true);
    const file = acceptedFiles[0];
    
    try {
      const { data: userData } = await supabase.auth.getUser();
      if (!userData.user) throw new Error("Authentication protocol required");

      const fileExt = file.name.split('.').pop();
      const fileName = `${Math.random()}.${fileExt}`;
      const filePath = `${userData.user.id}/${fileName}`;

      const { error: uploadError, data } = await supabase.storage
        .from('assets')
        .upload(filePath, file);

      if (uploadError) throw uploadError;

      const type = file.type.includes('pdf') ? 'pdf' : 
                   file.type.includes('video') ? 'video' : 
                   file.type.includes('presentation') || file.name.endsWith('pptx') ? 'pptx' : 'pdf';

      const { data: assetData, error: dbError } = await supabase
        .from('assets')
        .insert({
          filename: file.name,
          file_type: type,
          file_size: file.size,
          storage_url: data.path,
          user_id: userData.user.id,
          status: 'ready'
        })
        .select()
        .single();

      if (dbError) throw dbError;

      toast.success(`${file.name} ingested into Hive`);
      onUpload({
        label: file.name,
        type: type as 'pdf' | 'video' | 'pptx',
        id: assetData.id
      });
      onClose();
    } catch (error: any) {
      toast.error(error.message || "Ingestion protocol failure");
    } finally {
      setIsUploading(false);
    }
  }, [onUpload, onClose]);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "video/*": [".mp4", ".mov", ".avi"],
      "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"]
    },
    multiple: false
  });

  const filteredAssets = existingAssets.filter(asset => 
    asset.filename.toLowerCase().includes(searchQuery.toLowerCase())
  );

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
            className="relative w-full max-w-3xl bg-cream rounded-[2.5rem] shadow-2xl border border-wax overflow-hidden flex flex-col max-h-[85vh]"
          >
            {/* Header */}
            <div className="p-8 border-b border-wax flex justify-between items-center bg-white/50 backdrop-blur-xl shrink-0">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-honey/10 rounded-2xl">
                  <Database className="w-6 h-6 text-honey" />
                </div>
                <div>
                  <h2 className="text-2xl font-serif font-bold text-bee-black">Hive Assets</h2>
                  <p className="text-[10px] uppercase tracking-widest font-bold text-bee-black/40">Knowledge Source Management</p>
                </div>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-wax/50 rounded-full transition-colors cursor-pointer group">
                <X className="w-6 h-6 text-bee-black/20 group-hover:text-bee-black transition-colors" />
              </button>
            </div>

            <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col min-h-0">
              <div className="px-8 bg-white/30 border-b border-wax">
                <TabsList className="bg-transparent gap-8 h-14 p-0">
                  <TabsTrigger 
                    value="upload" 
                    className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-honey rounded-none h-full px-0 font-bold uppercase text-[10px] tracking-widest text-bee-black/40 data-[state=active]:text-bee-black"
                  >
                    Ingest New
                  </TabsTrigger>
                  <TabsTrigger 
                    value="workspace" 
                    className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 data-[state=active]:border-honey rounded-none h-full px-0 font-bold uppercase text-[10px] tracking-widest text-bee-black/40 data-[state=active]:text-bee-black"
                  >
                    Hive Library
                  </TabsTrigger>
                </TabsList>
              </div>

              <div className="flex-1 overflow-hidden">
                <TabsContent value="upload" className="h-full m-0 p-8 flex flex-col gap-8 overflow-y-auto">
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
                        {isUploading ? 'Processing knowledge layers...' : 'Drop source into the Hive'}
                      </p>
                      <p className="text-xs text-bee-black/40 font-medium uppercase tracking-widest">
                        PDF • MP4 • PPTX • (MAX 50MB)
                      </p>
                    </div>

                    {!isUploading && (
                      <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-bee-black/5 text-[9px] font-bold uppercase tracking-[0.2em] text-bee-black/40">
                        <Check size={10} className="text-green-500" /> Secure Protocol Active
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
                      { icon: FileText, label: 'Scientific Docs', sub: 'Technical Analysis', color: 'bg-blue-50 text-blue-500' },
                      { icon: Video, label: 'Lecture Visuals', sub: 'Visual Extraction', color: 'bg-purple-50 text-purple-500' },
                      { icon: Presentation, label: 'Architecture Decks', sub: 'Slide Synthesis', color: 'bg-orange-50 text-orange-500' }
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
                </TabsContent>

                <TabsContent value="workspace" className="h-full m-0 flex flex-col min-h-0">
                  <div className="p-8 pb-4 shrink-0">
                    <div className="relative">
                      <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-bee-black/20" />
                      <input 
                        type="text" 
                        placeholder="Search Hive assets..." 
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full h-12 pl-12 pr-4 bg-white/50 border border-wax rounded-2xl text-sm focus:outline-none focus:border-honey focus:ring-1 focus:ring-honey transition-all font-medium"
                      />
                    </div>
                  </div>

                  <ScrollArea className="flex-1 px-8">
                    <div className="grid grid-cols-1 gap-3 py-4 pb-8">
                      {isLoadingAssets ? (
                        <div className="py-20 flex flex-col items-center justify-center gap-4 text-bee-black/20">
                          <Loader2 className="w-8 h-8 animate-spin" />
                          <p className="text-[10px] uppercase tracking-widest font-bold">Querying Archive...</p>
                        </div>
                      ) : filteredAssets.length > 0 ? (
                        filteredAssets.map((asset) => (
                          <div 
                            key={asset.id}
                            className="group flex items-center justify-between p-4 bg-white hover:bg-honey/5 border border-wax hover:border-honey/20 rounded-[1.5rem] transition-all duration-300 cursor-pointer shadow-sm"
                            onClick={() => {
                              onUpload({
                                label: asset.filename,
                                type: asset.file_type as 'pdf' | 'video' | 'pptx',
                                id: asset.id
                              });
                              onClose();
                            }}
                          >
                            <div className="flex items-center gap-4 min-w-0">
                              <div className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 border border-wax bg-cream group-hover:bg-white transition-colors`}>
                                {asset.file_type === 'pdf' ? <FileText className="w-5 h-5 text-blue-500" /> :
                                 asset.file_type === 'video' ? <Video className="w-5 h-5 text-purple-500" /> :
                                 <Presentation className="w-5 h-5 text-orange-500" />}
                              </div>
                              <div className="min-w-0">
                                <h4 className="text-sm font-bold text-bee-black truncate uppercase tracking-tight">{asset.filename}</h4>
                                <div className="flex items-center gap-3 text-[9px] font-bold text-bee-black/30 uppercase tracking-widest mt-1">
                                  <span>{(asset.file_size / (1024 * 1024)).toFixed(1)} MB</span>
                                  <div className="w-1 h-1 rounded-full bg-wax" />
                                  <span>{new Date(asset.created_at).toLocaleDateString()}</span>
                                </div>
                              </div>
                            </div>
                            <div className="flex items-center gap-2">
                              <Button 
                                variant="ghost" 
                                size="icon" 
                                className="h-10 w-10 rounded-xl hover:bg-red-50 hover:text-red-500 text-bee-black/20 transition-colors"
                                onClick={async (e) => {
                                  e.stopPropagation();
                                  try {
                                    await api.assets.delete(asset.id);
                                    setExistingAssets(prev => prev.filter(a => asset.id !== a.id));
                                    toast.success("File deleted");
                                  } catch (error) {
                                    toast.error("Failed to delete");
                                  }
                                }}
                              >
                                <Trash2 size={16} />
                              </Button>
                              <div className="w-10 h-10 rounded-xl bg-honey/10 text-honey flex items-center justify-center group-hover:bg-honey group-hover:text-bee-black transition-all">
                                <Plus size={18} />
                              </div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="py-20 text-center space-y-4 opacity-30">
                          <Database className="w-12 h-12 mx-auto" />
                          <p className="text-[10px] font-bold uppercase tracking-widest">Archive is currently empty</p>
                        </div>
                      )}
                    </div>
                  </ScrollArea>
                </TabsContent>
              </div>

              {/* Footer */}
              <div className="p-8 border-t border-wax bg-cream/50 flex justify-between items-center shrink-0">
                <div className="flex items-center gap-2 text-bee-black/40">
                  <Check size={14} />
                  <span className="text-[10px] font-bold uppercase tracking-widest">End-to-End Encryption Active</span>
                </div>
                <div className="flex gap-3">
                  <Button variant="ghost" onClick={onClose} className="rounded-xl font-bold uppercase text-[10px] tracking-widest px-6 h-12">Decline</Button>
                  <Button className="rounded-xl bg-bee-black text-cream hover:bg-bee-black/90 font-bold uppercase text-[10px] tracking-widest px-8 h-12 gap-2 group">
                    Analyze Pipeline <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-1 transition-transform" />
                  </Button>
                </div>
              </div>
            </Tabs>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
