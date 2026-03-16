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
    <div className="flex flex-col min-h-screen bg-[#f7f0e8]">
      {/* Main layout with sidebar and content */}
      <div className="flex flex-1 overflow-hidden">
        {!isDocsPage && <Sidebar />}
        <div className={`flex-1 flex flex-col ${isDocsPage ? "" : "ml-52"}`}>
          {/* Single bar — logo left, command center, controls right */}
          <div className="h-11 border-b border-[#e5d5c5] flex items-center px-4 bg-[#f7f0e8] flex-shrink-0 z-50">
            {/* Left — logo (docs pages) */}
            <div className="flex items-center gap-2 w-48">
              {isDocsPage && (
                <Link href="/overview" className="flex items-center gap-2">
                  <svg width="20" height="20" viewBox="0 0 100 100" fill="none">
                    <circle cx="50" cy="50" r="8" fill="#b58a73"/>
                    <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#b58a73" strokeWidth="2.5" fill="none"/>
                    <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#b58a73" strokeWidth="2.5" fill="none" transform="rotate(60 50 50)"/>
                    <ellipse cx="50" cy="50" rx="35" ry="12" stroke="#b58a73" strokeWidth="2.5" fill="none" transform="rotate(120 50 50)"/>
                  </svg>
                  <span className="text-sm font-medium">Synthetic Sciences</span>
                </Link>
              )}
            </div>

            {/* Center — command button */}
            <div className="flex-1 flex justify-center">
              <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[#dfcdbf] text-xs text-[#a09488] hover:text-[#8a7a72] hover:border-[#c5b5a5] transition-colors">
                <Command size={12} />
                <span>command</span>
              </button>
            </div>

            {/* Right — search, user menu */}
            <div className="flex items-center gap-2 w-auto">
              <button className="flex items-center gap-2 px-3 py-1.5 bg-[#f7f0e8] border border-[#dfcdbf] rounded-md text-[11px] text-[#8a7a72] hover:text-[#695954] hover:border-[#c5b5a5] transition-colors">
                <Search size={11} className="opacity-60" />
                search...
                <kbd className="ml-1 text-[9px] text-[#a09488] px-1 py-0.5 bg-[#efe7dd] rounded border border-[#dfcdbf]">⌘K</kbd>
              </button>

              {/* User Menu */}
              <div className="relative" ref={menuRef}>
                <button
                  onClick={() => setShowUserMenu(!showUserMenu)}
                  className="px-2.5 py-1 bg-[#f7f0e8] border border-[#dfcdbf] rounded-md text-[10px] text-[#695954] hover:text-[#2e2522] hover:border-[#c5b5a5] transition-colors lowercase"
                >
                  {profile?.email ? profile.email.split('@')[0] : 'local'}
                </button>

                {showUserMenu && (
                  <div className="absolute right-0 top-full mt-1 w-56 bg-[#efe7dd] border border-[#dfcdbf] rounded-lg shadow-xl z-50 py-1">
                    <div className="px-3 py-2 border-b border-[#dfcdbf]">
                      <div className="text-[11px] text-[#8a7a72] lowercase">{profile?.email || 'local@localhost'}</div>
                      <div className="text-[10px] text-[#a09488] mt-0.5">local deployment</div>
                    </div>
                  </div>
                )}
              </div>
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
