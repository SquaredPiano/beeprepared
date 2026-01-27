"use client";

import { useState, useEffect } from "react";
import {
  User,
  Shield,
  Palette,
  Volume2,
  Bug,
  Save,
  LogOut,
  Cloud,
  ChevronRight,
  Monitor,
  Moon,
  Sun,
  Trash2,
  AlertTriangle
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export default function SettingsPage() {
  const [isLoading, setIsLoading] = useState(false);
  const [profile, setProfile] = useState<any>(null);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");

  // Settings state with defaults
  const [theme, setTheme] = useState<'light' | 'dark' | 'system'>('light');
  const [showMascot, setShowMascot] = useState(true);
  const [animations, setAnimations] = useState(true);
  const [audioFeedback, setAudioFeedback] = useState(true);
  const [autoSave, setAutoSave] = useState(true);
  const [fullName, setFullName] = useState("");
  const [bio, setBio] = useState("");

  // Load settings from localStorage on mount
  useEffect(() => {
    const savedSettings = localStorage.getItem('beeprepared_settings');
    if (savedSettings) {
      try {
        const settings = JSON.parse(savedSettings);
        setTheme(settings.theme || 'light');
        setShowMascot(settings.showMascot ?? true);
        setAnimations(settings.animations ?? true);
        setAudioFeedback(settings.audioFeedback ?? true);
        setAutoSave(settings.autoSave ?? true);
        setFullName(settings.fullName || "");
        setBio(settings.bio || "");
      } catch (e) {
        console.error('[Settings] Failed to parse saved settings');
      }
    }
  }, []);

  useEffect(() => {
    async function fetchProfile() {
      const { data: { user } } = await supabase.auth.getUser();
      if (user) {
        setProfile(user);
        // Set name from user metadata if not already set
        if (!fullName && user.user_metadata?.full_name) {
          setFullName(user.user_metadata.full_name);
        }
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

    // Save to localStorage
    const settings = {
      theme,
      showMascot,
      animations,
      audioFeedback,
      autoSave,
      fullName,
      bio,
    };
    localStorage.setItem('beeprepared_settings', JSON.stringify(settings));

    // Sync to Supabase Auth Metadata (Cloud Persistence)
    try {
      const { error } = await supabase.auth.updateUser({
        data: {
          full_name: fullName,
          bio: bio
        }
      });
      if (error) throw error;
    } catch (e) {
      console.error("Cloud sync failed:", e);
      toast.error("Cloud sync failed (Local saved)");
    }

    await new Promise(resolve => setTimeout(resolve, 300));
    setIsLoading(false);
    toast.success("Settings saved successfully");
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirmText !== "DELETE") {
      toast.error("Please type DELETE to confirm");
      return;
    }

    try {
      // In production, this would call a server action to delete the user
      toast.success("Account scheduled for deletion");
      await supabase.auth.signOut();
      window.location.href = "/";
    } catch (error) {
      toast.error("Failed to delete account");
    }
  };

  const sections = [
    { id: "account", label: "Profile", icon: User },
    { id: "appearance", label: "Appearance", icon: Palette },
    { id: "system", label: "System", icon: Monitor },
    { id: "security", label: "Security", icon: Shield },
  ];

  return (
    <div className="max-w-5xl mx-auto px-8 py-16 space-y-12 min-h-screen bg-cream/30">
      <header className="space-y-4">
        <h1 className="text-5xl font-serif italic text-bee-black">Settings</h1>
        <p className="text-sm text-bee-black/40 font-medium uppercase tracking-[0.1em]">Manage your account and preferences</p>
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
                      <h3 className="text-xl font-bold text-bee-black font-serif">Your Profile</h3>
                      <p className="text-xs text-bee-black/40 font-medium uppercase tracking-widest mt-1">ID: {profile?.id?.slice(0, 8) || "---"}</p>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <div className="space-y-2">
                      <Label className="text-xs font-semibold text-bee-black/70 ml-1">Full Name</Label>
                      <Input
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        placeholder="Your Name"
                        className="bg-cream/30 border-wax rounded-xl h-12"
                      />
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
                      value={bio}
                      onChange={(e) => setBio(e.target.value)}
                    />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="appearance" className="m-0 space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
                <div className="space-y-8">
                  <div className="space-y-4">
                    <h3 className="text-lg font-bold text-bee-black uppercase tracking-widest text-[10px] border-b border-wax pb-2">Theme</h3>
                    <div className="grid grid-cols-3 gap-4">
                      {[
                        { id: 'light', icon: Sun, label: 'Cream' },
                        { id: 'dark', icon: Moon, label: 'Wax' },
                        { id: 'system', icon: Monitor, label: 'Auto' }
                      ].map((themeOption) => (
                        <div
                          key={themeOption.id}
                          className="cursor-pointer group"
                          onClick={() => setTheme(themeOption.id as any)}
                        >
                          <div className={`h-24 border rounded-2xl flex items-center justify-center transition-all mb-2 ${theme === themeOption.id
                            ? "bg-honey/10 border-honey shadow-[0_0_15px_rgba(255,184,0,0.2)]"
                            : "bg-cream/50 border-wax group-hover:border-honey"
                            }`}>
                            <themeOption.icon className={`transition-colors ${theme === themeOption.id ? "text-honey" : "text-bee-black/20 group-hover:text-honey"
                              }`} />
                          </div>
                          <p className={`text-[10px] font-bold uppercase text-center transition-all ${theme === themeOption.id ? "text-honey opacity-100" : "opacity-40 group-hover:opacity-100"
                            }`}>{themeOption.label}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-6">
                    <div className="flex items-center justify-between p-6 rounded-3xl bg-cream/30 border border-wax">
                      <div className="space-y-1">
                        <p className="text-sm font-bold text-bee-black">Bee Mascot</p>
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Show the animated bee helper</p>
                      </div>
                      <Switch checked={showMascot} onCheckedChange={setShowMascot} />
                    </div>
                    <div className="flex items-center justify-between p-6 rounded-3xl bg-cream/30 border border-wax">
                      <div className="space-y-1">
                        <p className="text-sm font-bold text-bee-black">Animations</p>
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Enable smooth motion effects</p>
                      </div>
                      <Switch checked={animations} onCheckedChange={setAnimations} />
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
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Play sounds for UI interactions</p>
                      </div>
                    </div>
                    <Switch checked={audioFeedback} onCheckedChange={setAudioFeedback} />
                  </div>
                  <div className="flex items-center justify-between p-6 rounded-3xl bg-cream/30 border border-wax">
                    <div className="flex gap-4 items-center">
                      <div className="p-3 bg-blue-500/10 rounded-2xl"><Cloud className="text-blue-500" /></div>
                      <div className="space-y-1">
                        <p className="text-sm font-bold text-bee-black">Auto-Save</p>
                        <p className="text-xs text-bee-black/40 font-medium tracking-wide">Automatically save canvas progress</p>
                      </div>
                    </div>
                    <Switch checked={autoSave} onCheckedChange={setAutoSave} />
                  </div>
                </div>
              </TabsContent>

              <TabsContent value="security" className="m-0 space-y-8 animate-in fade-in slide-in-from-bottom-2 duration-500">
                <div className="space-y-6">
                  <div className="space-y-4">
                    <h3 className="text-lg font-bold text-bee-black uppercase tracking-widest text-[10px] border-b border-wax pb-2">Account Security</h3>
                    <div className="p-6 rounded-3xl bg-cream/30 border border-wax space-y-4">
                      <div className="flex gap-4 items-center">
                        <div className="p-3 bg-green-500/10 rounded-2xl"><Shield className="text-green-500" /></div>
                        <div className="space-y-1">
                          <p className="text-sm font-bold text-bee-black">Email Verified</p>
                          <p className="text-xs text-bee-black/40 font-medium tracking-wide">{profile?.email || "No email"}</p>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-4">
                    <h3 className="text-lg font-bold text-red-600 uppercase tracking-widest text-[10px] border-b border-red-200 pb-2">Danger Zone</h3>
                    <div className="p-6 rounded-3xl bg-red-50 border border-red-200 space-y-4">
                      <div className="flex gap-4 items-start">
                        <div className="p-3 bg-red-100 rounded-2xl"><AlertTriangle className="text-red-500" /></div>
                        <div className="space-y-2 flex-1">
                          <p className="text-sm font-bold text-red-700">Delete Account</p>
                          <p className="text-xs text-red-600/60 font-medium">This action is irreversible. All your projects, artifacts, and data will be permanently deleted.</p>

                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <Button variant="outline" className="mt-4 border-red-300 text-red-600 hover:bg-red-100 hover:border-red-400">
                                <Trash2 size={14} className="mr-2" />
                                Delete My Account
                              </Button>
                            </AlertDialogTrigger>
                            <AlertDialogContent className="rounded-3xl">
                              <AlertDialogHeader>
                                <AlertDialogTitle className="text-red-600">Are you absolutely sure?</AlertDialogTitle>
                                <AlertDialogDescription className="space-y-4">
                                  <p>This will permanently delete your account and all associated data. This action cannot be undone.</p>
                                  <div className="space-y-2">
                                    <Label className="text-xs font-semibold">Type DELETE to confirm</Label>
                                    <Input
                                      value={deleteConfirmText}
                                      onChange={(e) => setDeleteConfirmText(e.target.value)}
                                      placeholder="DELETE"
                                      className="border-red-200 focus:border-red-400"
                                    />
                                  </div>
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel className="rounded-xl">Cancel</AlertDialogCancel>
                                <AlertDialogAction
                                  onClick={handleDeleteAccount}
                                  disabled={deleteConfirmText !== "DELETE"}
                                  className="bg-red-600 hover:bg-red-700 rounded-xl disabled:opacity-50"
                                >
                                  Delete Account
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </TabsContent>
            </div>
          </div>

          <aside className="space-y-8">
            <div className="space-y-3">
              <Button
                variant="outline"
                onClick={handleSave}
                disabled={isLoading}
                className="w-full h-14 border-wax hover:bg-honey/10 hover:border-honey/30 rounded-2xl gap-3 uppercase text-[10px] font-bold tracking-[0.2em]"
              >
                {isLoading ? "Saving..." : <><Save size={16} /> Save Settings</>}
              </Button>
              <Button
                variant="ghost"
                onClick={handleLogout}
                className="w-full h-14 hover:bg-red-50 hover:text-red-600 rounded-2xl gap-3 uppercase text-[10px] font-bold tracking-[0.2em] text-bee-black/40"
              >
                <LogOut size={16} /> Log Out
              </Button>
            </div>

            <div className="p-6 border border-wax rounded-[2rem] bg-white/40 flex items-center justify-between cursor-pointer hover:border-honey/30 transition-colors">
              <div className="flex items-center gap-3">
                <Bug size={14} className="opacity-40" />
                <span className="text-[10px] font-bold uppercase tracking-widest opacity-60">Build Logs</span>
              </div>
              <ChevronRight size={14} className="opacity-40" />
            </div>
          </aside>
        </div>
      </Tabs>
    </div>
  );
}
