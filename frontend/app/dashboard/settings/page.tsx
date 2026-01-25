"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { 
  User, 
  Bell, 
  Shield, 
  Palette, 
  Volume2, 
  Bug,
  Save,
  LogOut,
  CreditCard,
  Cloud,
  ChevronRight,
  Monitor,
  Moon,
  Sun
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function SettingsPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [profile, setProfile] = useState<any>(null);

  useEffect(() => {
    async function fetchProfile() {
      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        setProfile(user);
      }
    }
    fetchProfile();
  }, []);

  const handleLogout = async () => {
    await supabase.auth.signOut();
    window.location.href = "/";
  };

  const handleSave = async () => {
    setIsLoading(true);
    await new Promise(resolve => setTimeout(resolve, 1000));
    setIsLoading(false);
    toast.success("Preferences updated in Hive Matrix");
  };

  const sections = [
    { id: "account", label: "Identity", icon: User },
    { id: "appearance", label: "Visuals", icon: Palette },
    { id: "system", label: "Operations", icon: Monitor },
    { id: "security", label: "Security", icon: Shield },
  ];

  return (
    <div className="max-w-5xl mx-auto px-8 py-16 space-y-12 min-h-screen bg-cream/30">
      <header className="space-y-4">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-honey/10 text-honey text-[10px] font-bold uppercase tracking-widest border border-honey/20">
          Hive Protocol v1.4.2
        </div>
        <h1 className="text-5xl font-serif italic text-bee-black">Settings</h1>
        <p className="text-sm text-bee-black/40 font-medium uppercase tracking-[0.1em]">Configure your knowledge architecture workspace</p>
      </header>

      <Tabs defaultValue="account" className="space-y-8">
        <div className="bg-white/60 backdrop-blur-xl border border-wax rounded-[2rem] p-2 inline-flex shadow-sm">
          <TabsList className="bg-transparent gap-2 h-auto p-0">
            {sections.map((section) => (
              <TabsTrigger 
                key={section.id}
                value={section.id} 
                className="data-[state=active]:bg-bee-black data-[state=active]:text-cream rounded-2xl px-6 py-3 font-bold uppercase text-[10px] tracking-widest text-bee-black/40 transition-all gap-2"
              >
                <section.icon size={14} />
                {section.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-12">
          <div className="lg:col-span-2">
            <div className="bg-white/80 backdrop-blur-xl border border-wax rounded-[2.5rem] p-10 shadow-sm min-h-[500px]">
              <TabsContent value="account" className="m-0 space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
                <div className="space-y-6">
                  <div className="flex items-center gap-6">
                    <div className="w-20 h-20 bg-honey/10 rounded-[2rem] flex items-center justify-center border-2 border-dashed border-honey/30 relative group cursor-pointer overflow-hidden">
                      <User size={32} className="text-honey group-hover:scale-110 transition-transform" />
                      <div className="absolute inset-0 bg-honey/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                        <Save size={20} className="text-bee-black" />
                      </div>
                    </div>
                    <div>
                      <h3 className="text-xl font-bold text-bee-black font-serif">Identity Profile</h3>
                      <p className="text-xs text-bee-black/40 font-medium uppercase tracking-widest mt-1">Worker {profile?.id?.slice(0, 8) || "000"}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <Label className="text-xs font-semibold text-bee-black/70 ml-1">Full Name</Label>
                      <Input defaultValue={profile?.user_metadata?.full_name || "New Worker"} className="bg-cream/30 border-wax rounded-xl h-12" />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs font-semibold text-bee-black/70 ml-1">Email</Label>
                      <Input defaultValue={profile?.email || ""} disabled className="bg-bee-black/5 border-wax rounded-xl h-12 opacity-50" />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <Label className="text-xs font-semibold text-bee-black/70 ml-1">Bio</Label>
                    <textarea 
                      className="w-full min-h-[100px] bg-cream/30 border border-wax rounded-2xl p-4 text-sm focus:outline-none focus:border-honey focus:ring-1 focus:ring-honey transition-all font-medium"
                      placeholder="Tell us about yourself..."
                    />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="appearance" className="m-0 space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
                <div className="space-y-8">
                  <div className="space-y-4">
                    <h3 className="text-lg font-bold text-bee-black uppercase tracking-widest text-[10px] border-b border-wax pb-2">Hive Interface</h3>
                    <div className="grid grid-cols-3 gap-4">
                      {[
                        { id: 'light', icon: Sun, label: 'Cream' },
                        { id: 'dark', icon: Moon, label: 'Wax' },
                        { id: 'system', icon: Monitor, label: 'Auto' }
                      ].map((theme) => (
                        <div key={theme.id} className="cursor-pointer group">
                          <div className="h-24 bg-cream/50 border border-wax rounded-2xl flex items-center justify-center group-hover:border-honey transition-all mb-2">
                            <theme.icon className="text-bee-black/20 group-hover:text-honey transition-colors" />
                          </div>
                          <p className="text-[10px] font-bold uppercase text-center opacity-40 group-hover:opacity-100">{theme.label}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-6">
                    <div className="flex items-center justify-between p-6 rounded-3xl bg-cream/30 border border-wax">
                      <div className="space-y-1">
                        <p className="text-sm font-bold text-bee-black">Bee Mascot Presence</p>
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Enable the architectural assistant animation</p>
                      </div>
                      <Switch defaultChecked />
                    </div>
                    <div className="flex items-center justify-between p-6 rounded-3xl bg-cream/30 border border-wax">
                      <div className="space-y-1">
                        <p className="text-sm font-bold text-bee-black">High-Fidelity Animations</p>
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Use GSAP for sophisticated motion effects</p>
                      </div>
                      <Switch defaultChecked />
                    </div>
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="system" className="m-0 space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
                <div className="space-y-6">
                  <div className="flex items-center justify-between p-6 rounded-3xl bg-cream/30 border border-wax">
                    <div className="flex gap-4 items-center">
                      <div className="p-3 bg-honey/10 rounded-2xl"><Volume2 className="text-honey" /></div>
                      <div className="space-y-1">
                        <p className="text-sm font-bold text-bee-black">Audio Feedback</p>
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Synthesized sounds for UI interactions</p>
                      </div>
                    </div>
                    <Switch defaultChecked />
                  </div>
                  <div className="flex items-center justify-between p-6 rounded-3xl bg-cream/30 border border-wax">
                    <div className="flex gap-4 items-center">
                      <div className="p-3 bg-blue-500/10 rounded-2xl"><Cloud className="text-blue-500" /></div>
                      <div className="space-y-1">
                        <p className="text-sm font-bold text-bee-black">Auto-Persist State</p>
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Automatically save canvas progress to the cloud</p>
                      </div>
                    </div>
                    <Switch defaultChecked />
                  </div>
                </div>
              </TabsContent>
            </div>
          </div>

          <aside className="space-y-8">
            <div className="p-8 bg-bee-black rounded-[2.5rem] text-cream space-y-6 shadow-2xl shadow-bee-black/20">
              <h3 className="text-sm font-bold uppercase tracking-[0.2em]">Hive Tier</h3>
              <div className="space-y-2">
                <div className="flex items-baseline gap-2">
                  <span className="text-4xl font-sans font-bold text-honey">BETA</span>
                  <span className="text-[10px] font-bold uppercase opacity-40">Architect</span>
                </div>
                <p className="text-[10px] uppercase font-bold tracking-widest text-cream/40 leading-relaxed">
                  You are currently operating on the founding worker protocol.
                </p>
              </div>
              <Button className="w-full bg-cream text-bee-black hover:bg-honey font-bold rounded-xl h-12 uppercase text-[10px] tracking-widest transition-all">
                Manage Protocol
              </Button>
            </div>

            <div className="space-y-3">
              <Button 
                variant="outline" 
                onClick={handleSave}
                disabled={isLoading}
                className="w-full h-14 border-wax hover:bg-honey/10 hover:border-honey/30 rounded-2xl gap-3 uppercase text-[10px] font-bold tracking-[0.2em]"
              >
                {isLoading ? "Synchronizing..." : <><Save size={16} /> Save Preferences</>}
              </Button>
              <Button 
                variant="ghost" 
                onClick={handleLogout}
                className="w-full h-14 hover:bg-red-50 hover:text-red-600 rounded-2xl gap-3 uppercase text-[10px] font-bold tracking-[0.2em] text-bee-black/40"
              >
                <LogOut size={16} /> Exit Hive Matrix
              </Button>
            </div>

            <div className="p-6 border border-wax rounded-[2rem] bg-white/40 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Bug size={14} className="opacity-20" />
                <span className="text-[10px] font-bold uppercase tracking-widest opacity-40">Build Logs</span>
              </div>
              <ChevronRight size={14} className="opacity-20" />
            </div>
          </aside>
        </div>
      </Tabs>
    </div>
  );
}
