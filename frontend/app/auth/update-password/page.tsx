"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Hexagon, Lock, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";
import { toast } from "sonner";

export default function UpdatePasswordPage() {
  const supabase = createClient();
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleUpdatePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (password !== confirmPassword) {
      toast.error("Passwords don't match");
      return;
    }

    if (password.length < 6) {
      toast.error("Password must be at least 6 characters");
      return;
    }

    setIsLoading(true);
    
    try {
      const { error } = await supabase.auth.updateUser({
        password: password
      });

      if (error) throw error;
      
      toast.success("Password updated successfully!");
      
      // Redirect to dashboard
      setTimeout(() => {
        router.replace("/dashboard");
      }, 1000);
    } catch (error: any) {
      toast.error(error.message || "Failed to update password");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white/80 backdrop-blur-xl border border-wax rounded-3xl p-8 shadow-2xl shadow-honey/5 overflow-hidden relative"
    >
      <div className="absolute top-0 right-0 p-4 opacity-5">
        <Hexagon size={120} className="text-honey fill-honey" />
      </div>

      <div className="space-y-6 relative z-10">
        <div className="space-y-2 text-center">
          <div className="flex justify-center mb-4">
            <div className="p-3 bg-honey rounded-2xl shadow-lg shadow-honey/20">
              <Hexagon className="w-8 h-8 text-bee-black fill-bee-black/10" />
            </div>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-bee-black font-serif italic">Create New Password</h1>
          <p className="text-sm text-bee-black/40 font-medium">Enter your new password below</p>
        </div>

        <form onSubmit={handleUpdatePassword} className="space-y-4">
          <div className="space-y-2">
            <div className="px-1">
              <Label htmlFor="password" className="text-xs font-semibold text-bee-black/70">New Password</Label>
            </div>
            <div className="relative group">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bee-black/20 group-focus-within:text-honey transition-colors" />
              <Input 
                id="password" 
                type="password" 
                placeholder="••••••••" 
                autoComplete="new-password"
                className="pl-10 h-12 bg-cream/30 border-wax focus:border-honey focus:ring-honey rounded-xl transition-all"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>
          </div>
          
          <div className="space-y-2">
            <div className="px-1">
              <Label htmlFor="confirmPassword" className="text-xs font-semibold text-bee-black/70">Confirm Password</Label>
            </div>
            <div className="relative group">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bee-black/20 group-focus-within:text-honey transition-colors" />
              <Input 
                id="confirmPassword" 
                type="password" 
                placeholder="••••••••" 
                autoComplete="new-password"
                className="pl-10 h-12 bg-cream/30 border-wax focus:border-honey focus:ring-honey rounded-xl transition-all"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={6}
              />
            </div>
          </div>

          <Button 
            type="submit" 
            className="w-full h-12 bg-bee-black hover:bg-bee-black/90 text-cream font-bold rounded-xl gap-2 group transition-all active:scale-95"
            disabled={isLoading}
          >
            {isLoading ? "Updating..." : "Update Password"}
            {!isLoading && <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />}
          </Button>
        </form>
      </div>
    </motion.div>
  );
}
