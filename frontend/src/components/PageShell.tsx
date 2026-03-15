"use client";

import Sidebar from "./Sidebar";
import { Command, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useRef } from "react";
import { getSupabase } from "@/lib/supabase";
import { useUserProfile } from "@/contexts/UserProfileContext";

const productTabs = [
  { label: "dashboard", href: "https://app.syntheticsciences.ai/dashboard", external: true },
  { label: "cli", href: "https://cli.syntheticsciences.ai", external: true },
  { label: "cloud", href: "https://app.inkvell.ai", external: true },
  { label: "context", href: "/overview", external: false },
];

function getTierColor(tier: string) {
  switch (tier) {
    case "lab": return "bg-purple-500/10 text-purple-400 border border-purple-500/20";
    case "researcher": return "bg-blue-500/10 text-blue-400 border border-blue-500/20";
    default: return "bg-[#1a1a1a] text-[#666] border border-[#1f1f1f]";
  }
}

export default function PageShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [userEmail, setUserEmail] = useState<string>("");
  const menuRef = useRef<HTMLDivElement>(null);
  const { profile } = useUserProfile();

  // Auth guard — redirect to login if no Supabase session or custom API key
  useEffect(() => {
    async function checkAuth() {
      // Check Supabase session first (handles auto-refresh)
      try {
        const { data } = await getSupabase().auth.getSession();
        if (data.session) {
          setAuthed(true);
          return;
        }
      } catch {
        // Supabase not configured — fall through
      }

      // Fallback: check for custom API key (e.g. synsc_894f…)
      const apiKey = localStorage.getItem("synsc_api_key");
      if (apiKey && apiKey.startsWith("synsc_")) {
        setAuthed(true);
        return;
      }

      // No valid auth — redirect to login
      router.replace("/");
    }
    checkAuth();
  }, [router]);

  // Fetch user email
  useEffect(() => {
    async function loadUserEmail() {
      try {
        const { data } = await getSupabase().auth.getSession();
        if (data.session?.user?.email) {
          setUserEmail(data.session.user.email);
        }
      } catch {
        // ignore
      }
    }
    loadUserEmail();
  }, []);

  // Close user menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setShowUserMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  async function handleSignOut() {
    try {
      await getSupabase().auth.signOut();
    } catch {
      // ignore
    }
    localStorage.removeItem("synsc_api_key");
    router.replace("/");
  }
  
  // This website is always the "context" tab
  const activeTab = "context";
  const isDocsPage = pathname.startsWith("/docs");

  // Show layout shell with loading indicator while checking auth (avoids blank screen)
  if (!authed) {
    return (
      <div className="flex flex-col min-h-screen bg-[#0a0a0a]">
        <header className="h-12 border-b border-[#1f1f1f] flex items-center px-3 bg-[#111111] flex-shrink-0">
          <div className="flex items-center gap-2">
            <svg width="20" height="20" viewBox="800 350 450 450" fill="none">
              <circle cx="1025" cy="575" r="120" fill="#fa7315" opacity="0.15" />
            </svg>
            <span className="text-xs text-[#333] lowercase tracking-wider">loading...</span>
          </div>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="w-5 h-5 border-2 border-[#fa7315] border-t-transparent rounded-full animate-spin" />
        </div>
      </div>
    );
  }
  
  return (
    <div className="flex flex-col min-h-screen bg-[#0a0a0a]">
      {/* Top bar - full width across entire screen */}
      <header className="h-12 border-b border-[#1f1f1f] flex items-center justify-between px-3 bg-[#111111] flex-shrink-0 z-50">
        {/* Left - Product tabs */}
        <div className="flex items-center gap-2">
          <nav className="flex items-center gap-0.5 p-[3px] bg-[#0a0a0a] border border-[#1f1f1f] rounded-lg">
            {productTabs.map((tab) => {
              const isActive = tab.label === activeTab;
              const TabComponent = tab.external ? 'a' : Link;
              const linkProps = tab.external 
                ? { href: tab.href, target: "_blank", rel: "noopener noreferrer" }
                : { href: tab.href };
              
              return (
                <TabComponent
                  key={tab.label}
                  {...linkProps}
                  className={`px-3 py-1.5 rounded-md text-[11px] font-semibold tracking-tight transition-all duration-100 whitespace-nowrap ${
                    isActive 
                      ? "bg-[#f97316] text-white shadow-[0_1px_4px_rgba(249,115,22,0.3)]" 
                      : "text-[#666] hover:text-[#999] hover:bg-[#1a1a1a]"
                  }`}
                >
                  {tab.label}
                </TabComponent>
              );
            })}
          </nav>
        </div>

        {/* Center - spacer */}
        <div className="flex-1" />

        {/* Right side - search, tier, credits, user menu */}
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-2 px-3 py-1.5 bg-[#0a0a0a] border border-[#1f1f1f] rounded-md text-[11px] text-[#666] hover:text-[#999] hover:border-[#2a2a2a] transition-colors">
            <Search size={11} className="opacity-60" />
            search...
            <kbd className="ml-1 text-[9px] text-[#444] px-1 py-0.5 bg-[#111] rounded border border-[#1f1f1f]">⌘K</kbd>
          </button>

          {/* Tier Button */}
          {profile && (
            <button
              onClick={() => window.open('https://app.syntheticsciences.ai/pricing', '_blank')}
              className={`px-2.5 py-1.5 rounded-md text-[11px] font-medium uppercase transition-colors ${getTierColor(profile.tier)}`}
            >
              {profile.tier}
            </button>
          )}

          {/* Credits Display */}
          {profile && (
            <span className="px-2.5 py-1.5 bg-[#0a0a0a] border border-[#1f1f1f] rounded-md text-[11px] text-[#999]">
              {profile.credits_used.toFixed(2)} / {profile.credits_limit} credits
            </span>
          )}

          {/* User Menu */}
          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="px-3 py-1.5 bg-[#0a0a0a] border border-[#1f1f1f] rounded-md text-[11px] text-[#999] hover:text-white hover:border-[#2a2a2a] transition-colors lowercase"
            >
              {userEmail ? userEmail.split('@')[0] : 'user'}
            </button>

            {showUserMenu && (
              <div className="absolute right-0 top-full mt-1 w-56 bg-[#111] border border-[#1f1f1f] rounded-lg shadow-xl z-50 py-1">
                {/* Header with email and credits */}
                <div className="px-3 py-2 border-b border-[#1f1f1f]">
                  <div className="text-[11px] text-[#666] lowercase">{userEmail}</div>
                  {profile && (
                    <div className="text-[10px] text-[#555] mt-0.5">
                      {profile.credits_used.toFixed(1)} / {profile.credits_limit} credits
                    </div>
                  )}
                </div>

                {/* Settings */}
                <button
                  onClick={() => {
                    window.open('https://app.syntheticsciences.ai/settings', '_blank');
                    setShowUserMenu(false);
                  }}
                  className="w-full px-3 py-1.5 text-left text-[11px] text-[#999] hover:text-white hover:bg-[#1a1a1a] transition-colors lowercase"
                >
                  settings
                </button>

                {/* Sign Out */}
                <button
                  onClick={() => {
                    handleSignOut();
                    setShowUserMenu(false);
                  }}
                  className="w-full px-3 py-1.5 text-left text-[11px] text-red-500 hover:text-red-400 hover:bg-[#1a1a1a] transition-colors lowercase"
                >
                  sign out
                </button>
              </div>
            )}
          </div>
        </div>
      </header>

      {/* Main layout with sidebar and content */}
      <div className="flex flex-1 overflow-hidden">
        {!isDocsPage && <Sidebar />}
        <div className={`flex-1 flex flex-col ${isDocsPage ? "" : "ml-52"}`}>
          {/* Command bar */}
          <div className="h-11 border-b border-[#151515] flex items-center px-6 bg-[#0a0a0a] relative">
            {isDocsPage && (
              <Link href="/overview" className="flex items-center gap-2 absolute left-4">
                <svg width="20" height="20" viewBox="0 0 100 100" fill="none">
                  <circle cx="50" cy="50" r="8" fill="#fa7315"/>
                  <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#fa7315" strokeWidth="2.5" fill="none"/>
                  <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#fa7315" strokeWidth="2.5" fill="none" transform="rotate(60 50 50)"/>
                  <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#fa7315" strokeWidth="2.5" fill="none" transform="rotate(120 50 50)"/>
                </svg>
                <span className="text-sm font-medium">Synthetic Sciences</span>
              </Link>
            )}
            <div className="flex-1 flex justify-center">
              <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[#1a1a1a] text-xs text-[#444] hover:text-[#666] hover:border-[#222] transition-colors">
                <Command size={12} />
                <span>command</span>
              </button>
            </div>
          </div>
          
          {/* Main content */}
          <main className="flex-1 overflow-y-auto">
            <div className={`px-6 py-8 ${isDocsPage ? "max-w-none" : "mx-auto max-w-5xl"}`}>
              {children}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
