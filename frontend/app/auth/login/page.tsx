"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Hexagon, Mail, Lock, ArrowRight, Chrome } from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";
import { toast } from "sonner";

export default function LoginPage() {
  const supabase = createClient();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    try {
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (error) throw error;
      
      toast.success("Welcome back to the hive!");
      
      // Use replace to prevent back button issues
      router.replace("/dashboard");
    } catch (error: any) {
      toast.error(error.message || "Failed to login");
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleLogin = async () => {
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      });
      if (error) throw error;
    } catch (error: any) {
      toast.error(error.message || "Failed to start Google login");
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
          <h1 className="text-2xl font-bold tracking-tight text-bee-black font-serif italic">Welcome Back</h1>
          <p className="text-sm text-bee-black/40 font-medium uppercase tracking-[0.1em]">Enter the Hive to continue</p>
        </div>

        <form onSubmit={handleLogin} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email" className="text-[10px] font-bold uppercase tracking-widest text-bee-black/60 ml-1">Email Protocol</Label>
            <div className="relative group">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bee-black/20 group-focus-within:text-honey transition-colors" />
              <Input 
                id="email" 
                type="email" 
                placeholder="worker@hive.com" 
                className="pl-10 h-12 bg-cream/30 border-wax focus:border-honey focus:ring-honey rounded-xl transition-all"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between px-1">
              <Label htmlFor="password" title="Password" className="text-[10px] font-bold uppercase tracking-widest text-bee-black/60">Access Cipher</Label>
              <Link href="#" className="text-[10px] font-bold uppercase tracking-widest text-honey hover:underline">Forgot?</Link>
            </div>
            <div className="relative group">
              <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bee-black/20 group-focus-within:text-honey transition-colors" />
              <Input 
                id="password" 
                type="password" 
                placeholder="••••••••" 
                className="pl-10 h-12 bg-cream/30 border-wax focus:border-honey focus:ring-honey rounded-xl transition-all"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>
          <Button 
            type="submit" 
            className="w-full h-12 bg-bee-black hover:bg-bee-black/90 text-cream font-bold rounded-xl gap-2 group transition-all active:scale-95"
            disabled={isLoading}
          >
            {isLoading ? "Authenticating..." : "Synchronize Access"}
            {!isLoading && <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />}
          </Button>
        </form>

        <div className="relative py-2">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-wax"></div>
          </div>
          <div className="relative flex justify-center text-[10px] font-bold uppercase tracking-widest">
            <span className="bg-white px-4 text-bee-black/30">Or alternate relay</span>
          </div>
        </div>

        <Button 
          variant="outline" 
          className="w-full h-12 border-wax hover:bg-honey/5 hover:border-honey/30 rounded-xl gap-2 font-bold transition-all active:scale-95"
          onClick={handleGoogleLogin}
        >
          <Chrome className="w-4 h-4" />
          Continue with Google
        </Button>

        <p className="text-center text-xs font-medium text-bee-black/40">
          New to BeePrepared?{" "}
          <Link href="/auth/signup" className="text-honey font-bold hover:underline">Register your Hive</Link>
        </p>
      </div>
    </motion.div>
  );
}
