"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Hexagon, Mail, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { motion } from "framer-motion";
import { toast } from "sonner";

export default function ResetPasswordPage() {
  const supabase = createClient();
  const [email, setEmail] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [emailSent, setEmailSent] = useState(false);

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    
    try {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/auth/update-password`,
      });

      if (error) throw error;
      
      setEmailSent(true);
      toast.success("Password reset email sent! Check your inbox.");
    } catch (error: any) {
      toast.error(error.message || "Failed to send reset email");
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
          <h1 className="text-2xl font-bold tracking-tight text-bee-black font-serif italic">
            {emailSent ? "Check Your Email" : "Reset Password"}
          </h1>
          <p className="text-sm text-bee-black/40 font-medium">
            {emailSent 
              ? "We've sent you a link to reset your password" 
              : "Enter your email to receive a reset link"
            }
          </p>
        </div>

        {!emailSent ? (
          <form onSubmit={handleResetPassword} className="space-y-4">
            <div className="space-y-2">
              <div className="px-1">
                <Label htmlFor="email" className="text-xs font-semibold text-bee-black/70">Email</Label>
              </div>
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
            <Button 
              type="submit" 
              className="w-full h-12 bg-bee-black hover:bg-bee-black/90 text-cream font-bold rounded-xl transition-all active:scale-95"
              disabled={isLoading}
            >
              {isLoading ? "Sending..." : "Send Reset Link"}
            </Button>
          </form>
        ) : (
          <div className="space-y-4 py-4">
            <div className="text-center p-6 bg-honey/10 rounded-xl border border-honey/20">
              <p className="text-sm text-bee-black/60 font-medium">
                Click the link in your email to create a new password. The link will expire in 1 hour.
              </p>
            </div>
            <Button 
              onClick={() => setEmailSent(false)}
              variant="outline"
              className="w-full h-12 border-wax hover:bg-honey/5 hover:border-honey/30 rounded-xl font-bold transition-all active:scale-95"
            >
              Didn't receive it? Try again
            </Button>
          </div>
        )}

        <Link 
          href="/auth/login" 
          className="flex items-center justify-center gap-2 text-xs font-semibold text-bee-black/60 hover:text-honey transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to login
        </Link>
      </div>
    </motion.div>
  );
}
