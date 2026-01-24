"use client";

import { 
  Dialog, 
  DialogContent, 
  DialogHeader, 
  DialogTitle, 
  DialogDescription,
  DialogFooter
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HelpCircle, Mail, MessageSquare, Send, Check } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

interface SupportModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SupportModal({ isOpen, onClose }: SupportModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsCheck] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    
    // Simulate support ticket creation
    await new Promise(resolve => setTimeout(resolve, 1500));
    
    setIsSubmitting(false);
    setIsCheck(true);
    toast.success("Support ticket logged in Hive Archive");
    
    setTimeout(() => {
      setIsCheck(false);
      onClose();
    }, 2000);
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-md bg-cream border-wax rounded-[2.5rem] shadow-2xl overflow-hidden p-0">
        <div className="p-8 space-y-6">
          <DialogHeader>
            <div className="flex items-center gap-4 mb-4">
              <div className="p-3 bg-honey/10 rounded-2xl">
                <HelpCircle className="w-6 h-6 text-honey" />
              </div>
              <div>
                <DialogTitle className="text-2xl font-serif">Hive Support</DialogTitle>
                <DialogDescription className="text-[10px] font-bold uppercase tracking-widest text-bee-black/40">
                  Worker Assistance Protocol
                </DialogDescription>
              </div>
            </div>
          </DialogHeader>

          {isSuccess ? (
            <div className="py-12 flex flex-col items-center justify-center text-center space-y-4 animate-in zoom-in-95 duration-500">
              <div className="w-20 h-20 bg-green-500/10 rounded-full flex items-center justify-center mb-4">
                <Check className="w-10 h-10 text-green-500" />
              </div>
              <h3 className="text-xl font-bold text-bee-black">Protocol Logged</h3>
              <p className="text-sm text-bee-black/40 max-w-[240px]">A senior worker will analyze your query and relay a response shortly.</p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label className="text-[10px] font-bold uppercase tracking-widest text-bee-black/60 ml-1">Subject</Label>
                <Input 
                  placeholder="e.g. Ingestion pipeline error" 
                  className="bg-white/50 border-wax rounded-xl h-12"
                  required
                />
              </div>
              <div className="space-y-2">
                <Label className="text-[10px] font-bold uppercase tracking-widest text-bee-black/60 ml-1">Detailed Relay</Label>
                <textarea 
                  className="w-full min-h-[120px] bg-white/50 border border-wax rounded-2xl p-4 text-sm focus:outline-none focus:border-honey focus:ring-1 focus:ring-honey transition-all font-medium"
                  placeholder="Describe your issue in detail..."
                  required
                />
              </div>
              <Button 
                type="submit" 
                className="w-full h-12 bg-bee-black hover:bg-bee-black/90 text-cream rounded-xl font-bold uppercase text-[10px] tracking-widest gap-2 group transition-all"
                disabled={isSubmitting}
              >
                {isSubmitting ? "Transmitting..." : "Send Support Request"}
                {!isSubmitting && <Send className="w-3.5 h-3.5 group-hover:translate-x-1 group-hover:-translate-y-1 transition-transform" />}
              </Button>
            </form>
          )}
        </div>

        <div className="bg-white/50 backdrop-blur-xl border-t border-wax p-6 flex items-center justify-between">
          <div className="flex items-center gap-3 text-bee-black/40">
            <Mail size={14} />
            <span className="text-[10px] font-bold uppercase tracking-widest">support@beeprepared.ai</span>
          </div>
          <div className="flex items-center gap-3 text-bee-black/40">
            <MessageSquare size={14} />
            <span className="text-[10px] font-bold uppercase tracking-widest text-honey hover:underline cursor-pointer">Live Chat</span>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
