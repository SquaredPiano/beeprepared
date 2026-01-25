'use client'

import { createClient } from '@/lib/supabase/client'
import { useState } from 'react'

export default function SupabaseAuthTest() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [user, setUser] = useState<any>(null)
  const supabase = createClient()

  async function signUp() {
    setLoading(true)
    setMessage('')
    try {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
      })
      if (error) {
        setMessage(`❌ Sign Up Error: ${error.message}`)
      } else {
        setMessage(`✅ Sign Up Success! Check your email to confirm.`)
        setEmail('')
        setPassword('')
      }
    } catch (err: any) {
      setMessage(`❌ Unexpected Error: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function signIn() {
    setLoading(true)
    setMessage('')
    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      })
      if (error) {
        setMessage(`❌ Sign In Error: ${error.message}`)
      } else {
        setMessage(`✅ Sign In Success!`)
        setUser(data.user)
        setEmail('')
        setPassword('')
      }
    } catch (err: any) {
      setMessage(`❌ Unexpected Error: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function signInWithGoogle() {
    setLoading(true)
    setMessage('')
    try {
      const { data, error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: {
          redirectTo: `${window.location.origin}/test/supabase-auth`,
        },
      })
      if (error) {
        setMessage(`❌ Google Sign In Error: ${error.message}`)
      }
    } catch (err: any) {
      setMessage(`❌ Unexpected Error: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function signOut() {
    setLoading(true)
    try {
      const { error } = await supabase.auth.signOut()
      if (error) {
        setMessage(`❌ Sign Out Error: ${error.message}`)
      } else {
        setMessage(`✅ Signed Out`)
        setUser(null)
      }
    } catch (err: any) {
      setMessage(`❌ Unexpected Error: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  async function checkSession() {
    try {
      const { data, error } = await supabase.auth.getSession()
      if (error) {
        setMessage(`❌ Session Check Error: ${error.message}`)
      } else if (data.session) {
        setMessage(`✅ Active Session Found!`)
        setUser(data.session.user)
      } else {
        setMessage(`⚠️ No active session`)
        setUser(null)
      }
    } catch (err: any) {
      setMessage(`❌ Error: ${err.message}`)
    }
  }

  return (
    <div className="flex flex-col gap-6 max-w-md mx-auto mt-20 p-8 border border-gray-300 rounded-lg shadow-lg">
      <h1 className="text-2xl font-bold">🐝 Supabase Auth Test</h1>

      {user && (
        <div className="bg-green-100 border border-green-400 p-4 rounded">
          <p className="text-sm font-semibold">✅ Logged In:</p>
          <p className="text-xs text-gray-700">{user.email}</p>
          <p className="text-xs text-gray-600">ID: {user.id.slice(0, 8)}...</p>
        </div>
      )}

      {message && (
        <div className={`p-3 rounded text-sm ${message.includes('✅') ? 'bg-green-50 text-green-700' : message.includes('⚠️') ? 'bg-yellow-50 text-yellow-700' : 'bg-red-50 text-red-700'}`}>
          {message}
        </div>
      )}

      <div className="space-y-2">
        <input
          className="w-full border border-gray-300 p-3 rounded"
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={loading || !!user}
        />
        <input
          className="w-full border border-gray-300 p-3 rounded"
          type="password"
          placeholder="Password (min 6 chars)"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={loading || !!user}
        />
      </div>

      <div className="flex gap-2">
        <button
          onClick={signUp}
          disabled={loading || !!user || !email || !password}
          className="flex-1 bg-blue-500 text-white p-2 rounded font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:bg-blue-600"
        >
          {loading ? 'Loading...' : 'Sign Up'}
        </button>
        <button
          onClick={signIn}
          disabled={loading || !!user || !email || !password}
          className="flex-1 bg-green-500 text-white p-2 rounded font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:bg-green-600"
        >
          {loading ? 'Loading...' : 'Sign In'}
        </button>
      </div>

      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-gray-300"></div>
        </div>
        <div className="relative flex justify-center text-sm">
          <span className="px-2 bg-white text-gray-500">OR</span>
        </div>
      </div>

      <button
        onClick={signInWithGoogle}
        disabled={loading || !!user}
        className="w-full flex items-center justify-center gap-3 bg-white border border-gray-300 text-gray-700 p-2 rounded font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50"
      >
        <svg className="w-5 h-5" viewBox="0 0 24 24">
          <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
          <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
          <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
          <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
        </svg>
        {loading ? 'Loading...' : 'Sign in with Google'}
      </button>

      {user && (
        <button
          onClick={signOut}
          disabled={loading}
          className="w-full bg-red-500 text-white p-2 rounded font-semibold disabled:opacity-50 hover:bg-red-600"
        >
          {loading ? 'Loading...' : 'Sign Out'}
        </button>
      )}

      <button
        onClick={checkSession}
        disabled={loading}
        className="w-full bg-gray-500 text-white p-2 rounded text-sm disabled:opacity-50 hover:bg-gray-600"
      >
        Check Session
      </button>

      <div className="text-xs text-gray-500 bg-gray-50 p-3 rounded">
        <p className="font-semibold mb-2">📝 Test Instructions:</p>
        <ol className="list-decimal list-inside space-y-1">
          <li>Enter email & password</li>
          <li>Click "Sign Up" (creates account)</li>
          <li>Click "Sign In" (logs in)</li>
          <li>Click "Check Session" (verifies token)</li>
          <li>Click "Sign Out" (clears session)</li>
        </ol>
      </div>

      <div className="text-xs text-gray-500 border-t pt-3">
        <p className="font-semibold">🔐 Environment:</p>
        <p>URL: {process.env.NEXT_PUBLIC_SUPABASE_URL?.slice(0, 30)}...</p>
        <p>Key: {process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.slice(0, 20)}...</p>
      </div>
    </div>
  )
}
