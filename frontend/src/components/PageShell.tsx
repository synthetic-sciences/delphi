"use client";

import Sidebar from "./Sidebar";
import { Command, Search } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, useRef } from "react";
import { useUserProfile } from "@/contexts/UserProfileContext";

export default function PageShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [showUserMenu, setShowUserMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const { profile } = useUserProfile();

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

  const isDocsPage = pathname.startsWith("/docs");

  return (
    <div className="flex flex-col min-h-screen bg-[#0a0a0a]">
      {/* Top bar */}
      <header className="h-12 border-b border-[#1f1f1f] flex items-center justify-between px-3 bg-[#111111] flex-shrink-0 z-50">
        <div className="flex items-center gap-2">
          <Link href="/overview" className="flex items-center gap-2 px-3 py-1.5 rounded-md text-[11px] font-semibold tracking-tight text-white">
            delphi
          </Link>
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-2">
          <button className="flex items-center gap-2 px-3 py-1.5 bg-[#0a0a0a] border border-[#1f1f1f] rounded-md text-[11px] text-[#666] hover:text-[#999] hover:border-[#2a2a2a] transition-colors">
            <Search size={11} className="opacity-60" />
            search...
            <kbd className="ml-1 text-[9px] text-[#444] px-1 py-0.5 bg-[#111] rounded border border-[#1f1f1f]">⌘K</kbd>
          </button>

          {/* User Menu */}
          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setShowUserMenu(!showUserMenu)}
              className="px-3 py-1.5 bg-[#0a0a0a] border border-[#1f1f1f] rounded-md text-[11px] text-[#999] hover:text-white hover:border-[#2a2a2a] transition-colors lowercase"
            >
              {profile?.email ? profile.email.split('@')[0] : 'local'}
            </button>

            {showUserMenu && (
              <div className="absolute right-0 top-full mt-1 w-56 bg-[#111] border border-[#1f1f1f] rounded-lg shadow-xl z-50 py-1">
                <div className="px-3 py-2 border-b border-[#1f1f1f]">
                  <div className="text-[11px] text-[#666] lowercase">{profile?.email || 'local@localhost'}</div>
                  <div className="text-[10px] text-[#555] mt-0.5">local deployment</div>
                </div>
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
