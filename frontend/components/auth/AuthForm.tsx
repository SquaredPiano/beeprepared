'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { motion, AnimatePresence } from 'framer-motion'
import { Mail, Lock, Loader2, Github, ArrowRight } from 'lucide-react'

export function AuthForm() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const supabase = createClient()

  const handleEmailAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)

    try {
      if (mode === 'login') {
        const { error } = await supabase.auth.signInWithPassword({
          email,
          password,
        })
        if (error) throw error
        toast.success('Successfully logged in!')
        window.location.href = '/dashboard/canvas'
      } else {
        const { error } = await supabase.auth.signUp({
          email,
          password,
          options: {
            emailRedirectTo: `${window.location.origin}/auth/callback`,
          },
        })
        if (error) throw error
        toast.success('Check your email to confirm your account!')
      }
    } catch (error: any) {
      toast.error(error.message)
    } finally {
      setIsLoading(false)
    }
  }

  const handleGoogleAuth = async () => {
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/auth/callback`,
        },
      })
      if (error) throw error
    } catch (error: any) {
      toast.error(error.message)
    }
  }

  return (
    <div className="w-full max-w-md space-y-8 p-8 bg-cream/50 backdrop-blur-xl rounded-3xl border border-wax shadow-2xl">
      <div className="text-center space-y-2">
        <h1 className="text-4xl font-serif text-bee-black">
          {mode === 'login' ? 'Welcome Back' : 'Create Account'}
        </h1>
        <p className="text-bee-black/60 font-sans">
          {mode === 'login' 
            ? 'Continue your architectural journey' 
            : 'Begin your knowledge synthesis'}
        </p>
      </div>

      <div className="space-y-4">
        <Button 
          variant="outline" 
          className="w-full h-12 rounded-xl border-wax bg-white hover:bg-wax/20 text-bee-black transition-all duration-300 gap-3"
          onClick={handleGoogleAuth}
        >
          <svg className="w-5 h-5" viewBox="0 0 24 24">
            <path
              d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
              fill="#4285F4"
            />
            <path
              d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
              fill="#34A853"
            />
            <path
              d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.85z"
              fill="#FBBC05"
            />
            <path
              d="M12 5.38c1.62 0 3.06.56 4.21 1.66l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
              fill="#EA4335"
            />
          </svg>
          Continue with Google
        </Button>

        <div className="relative">
          <div className="absolute inset-0 flex items-center">
            <span className="w-full border-t border-wax" />
          </div>
          <div className="relative flex justify-center text-xs uppercase">
            <span className="bg-cream px-2 text-bee-black/40">Or continue with email</span>
          </div>
        </div>

        <form onSubmit={handleEmailAuth} className="space-y-4">
          <div className="space-y-2">
            <div className="relative">
              <Mail className="absolute left-3 top-3 h-5 w-5 text-bee-black/30" />
              <input
                type="email"
                placeholder="Email address"
                className="w-full h-12 pl-10 pr-4 rounded-xl border border-wax bg-white focus:ring-2 focus:ring-honey outline-none transition-all"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="relative">
              <Lock className="absolute left-3 top-3 h-5 w-5 text-bee-black/30" />
              <input
                type="password"
                placeholder="Password"
                className="w-full h-12 pl-10 pr-4 rounded-xl border border-wax bg-white focus:ring-2 focus:ring-honey outline-none transition-all"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </div>

          <Button 
            className="w-full h-12 rounded-xl bg-bee-black hover:bg-bee-black/90 text-cream transition-all duration-300"
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : (
              <span className="flex items-center gap-2">
                {mode === 'login' ? 'Sign In' : 'Create Account'}
                <ArrowRight className="h-4 w-4" />
              </span>
            )}
          </Button>
        </form>
      </div>

      <div className="text-center pt-4">
        <button
          onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}
          className="text-sm text-bee-black/60 hover:text-honey transition-colors"
        >
          {mode === 'login' 
            ? "Don't have an account? Sign up" 
            : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  )
}
