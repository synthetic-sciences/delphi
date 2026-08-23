"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  BookOpen,
  Code2,
  Database,
  FileText,
  Key,
  Shield,
  Workflow,
} from "lucide-react";
import { useUserProfile } from "@/contexts/UserProfileContext";

type NavEntry =
  | { icon: typeof BarChart3; label: string; href: string }
  | { separator: string };

const nav: NavEntry[] = [
  { icon: BarChart3, label: "overview", href: "/overview" },
  { icon: Workflow, label: "workspace", href: "/workspace" },
  { icon: Activity, label: "activity", href: "/activity" },
  { icon: FileText, label: "papers", href: "/papers" },
  { icon: Database, label: "datasets", href: "/datasets" },
  { icon: Code2, label: "repositories", href: "/repositories" },
  { separator: "account" },
  { icon: Key, label: "api keys", href: "/api-keys" },
  { icon: BookOpen, label: "docs", href: "/docs" },
];

const adminNav: NavEntry[] = [
  { separator: "admin" },
  { icon: Shield, label: "admin", href: "/admin/repos" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { profile } = useUserProfile();
  const items = profile?.is_admin ? [...nav, ...adminNav] : nav;

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-52 bg-[#f7f0e8] border-r border-[#e5d5c5] flex flex-col">
      <Link
        href="/overview"
        className="flex items-center gap-2.5 px-4 h-12 border-b border-[#e5d5c5]"
      >
        <Image aria-hidden="true" alt="" height={21} src="/icon.svg" width={21} />
        <span className="text-sm font-medium text-[#2e2522]">Delphi</span>
      </Link>

      <nav className="flex-1 px-2 py-3 overflow-y-auto">
        {items.map((item) => {
          if ("separator" in item) {
            return <div key={item.separator} className="h-4" />;
          }

          const active =
            pathname === item.href || pathname.startsWith(`${item.href}/`);

          return (
            <Link
              key={item.label}
              href={item.href}
              className={`group flex items-center gap-3 px-3 py-2 rounded-lg text-sm lowercase transition-all duration-200 ${
                active
                  ? "text-[#9a3f10] bg-[#faebd5] shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]"
                  : "text-[#8a7a72] hover:text-[#2e2522] hover:bg-[#faf5ef]"
              }`}
            >
              <span
                className={`transition-transform duration-200 ${
                  active ? "scale-110 text-[#d06e28]" : "group-hover:scale-110"
                }`}
              >
                <item.icon size={16} />
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
