"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Hexagon, Mail, Lock, ArrowRight, Chrome, User } from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";
import { toast } from "sonner";

export default function SignupPage() {
  const supabase = createClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    try {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: {
          data: {
            full_name: fullName,
          }
        }
      });

      if (error) throw error;
      
      toast.success("Account created! Please check your email to verify.");
    } catch (error: any) {
      toast.error(error.message || "Failed to register");
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
      toast.error(error.message || "Failed to start Google registration");
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
          <h1 className="text-2xl font-bold tracking-tight text-bee-black font-serif italic">Create Your Account</h1>
          <p className="text-sm text-bee-black/40 font-medium">Start building your knowledge today</p>
        </div>

        <form onSubmit={handleSignup} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name" className="text-xs font-semibold text-bee-black/70 ml-1">Full Name</Label>
            <div className="relative group">
              <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bee-black/20 group-focus-within:text-honey transition-colors" />
              <Input 
                id="name" 
                type="text" 
                placeholder="Your name" 
                autoComplete="name"
                className="pl-10 h-12 bg-cream/30 border-wax focus:border-honey focus:ring-honey rounded-xl transition-all"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="email" className="text-xs font-semibold text-bee-black/70 ml-1">Email</Label>
            <div className="relative group">
              <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bee-black/20 group-focus-within:text-honey transition-colors" />
              <Input 
                id="email" 
                type="email" 
                placeholder="you@example.com" 
                autoComplete="email"
                className="pl-10 h-12 bg-cream/30 border-wax focus:border-honey focus:ring-honey rounded-xl transition-all"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="password" className="text-xs font-semibold text-bee-black/70 ml-1">Password</Label>
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
              />
            </div>
          </div>
          <Button 
            type="submit" 
            className="w-full h-12 bg-bee-black hover:bg-bee-black/90 text-cream font-bold rounded-xl gap-2 group transition-all active:scale-95"
            disabled={isLoading}
          >
            {isLoading ? "Creating account..." : "Create Account"}
            {!isLoading && <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />}
          </Button>
        </form>

        <div className="relative py-2">
          <div className="absolute inset-0 flex items-center">
            <div className="w-full border-t border-wax"></div>
          </div>
          <div className="relative flex justify-center text-xs font-medium">
            <span className="bg-white px-4 text-bee-black/40">Or continue with</span>
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
          Already have an account?{" "}
          <Link href="/auth/login" className="text-honey font-bold hover:underline">Sign in</Link>
        </p>
      </div>
    </motion.div>
  );
}
