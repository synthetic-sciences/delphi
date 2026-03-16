"use client";

import PageShell from "@/components/PageShell";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer, XAxis } from "recharts";
import { useEffect, useState } from "react";
import { getAuthHeaders, API_URL } from "@/lib/api";
import { useUserProfile } from "@/contexts/UserProfileContext";

interface Stats {
  repos: number;
  papers: number;
  searches: number;
  toolCalls: number;
  apiUsage: number;
  apiChange: number;
  recentQueries: { q: string; t: string }[];
  chartData: { d: string; v: number }[];
}

export default function OverviewPage() {
  const { profile } = useUserProfile();
  const [stats, setStats] = useState<Stats>({
    repos: 0,
    papers: 0,
    searches: 0,
    toolCalls: 0,
    apiUsage: 0,
    apiChange: 0,
    recentQueries: [],
    chartData: [],
  });

  // Fetch stats from backend
  useEffect(() => {
    async function fetchStats() {
      try {
        const headers = await getAuthHeaders();

        // Fetch repos, papers, activity stats in parallel
        const [reposRes, papersRes, activityRes, weekRes] = await Promise.all([
          fetch(`${API_URL}/v1/repositories?limit=1`, { headers }).catch(() => null),
          fetch(`${API_URL}/v1/papers?limit=1`, { headers }).catch(() => null),
          fetch(`${API_URL}/v1/activity/stats?time_range=7d`, { headers }).catch(() => null),
          fetch(`${API_URL}/v1/activity?time_range=7d&limit=500`, { headers }).catch(() => null),
        ]);

        let repos = 0;
        let papers = 0;
        let searches = 0;
        let toolCalls = 0;

        // Repos count
        if (reposRes?.ok) {
          const data = await reposRes.json();
          repos = data.total ?? (data.repositories?.length || 0);
        }

        // Papers count
        if (papersRes?.ok) {
          const data = await papersRes.json();
          papers = data.total ?? (data.papers?.length || 0);
        }

        // Activity stats — extract search + total counts
        if (activityRes?.ok) {
          const data = await activityRes.json();
          if (data.success && data.stats) {
            toolCalls = data.stats.total || 0;
            const byAction = data.stats.by_action || {};
            searches = (byAction.search_code || 0) + (byAction.search_papers || 0) + (byAction.search_symbols || 0);
          }
        }

        // Build chart data + recent queries from weekly activity
        let chartData: { d: string; v: number }[] = [];
        let apiChange = 0;
        let recentQueries: { q: string; t: string }[] = [];
        let apiUsage = toolCalls;

        if (weekRes?.ok) {
          const weekData = await weekRes.json();
          if (weekData.success && weekData.activities) {
            const activities = weekData.activities as { action?: string; query?: string; created_at: string }[];

            // Build daily chart data for last 7 days
            const dayNames = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
            const buckets: Record<string, number> = {};
            const today = new Date();

            for (let i = 6; i >= 0; i--) {
              const d = new Date(today);
              d.setDate(d.getDate() - i);
              const key = d.toISOString().slice(0, 10);
              buckets[key] = 0;
            }

            for (const a of activities) {
              const key = a.created_at?.slice(0, 10);
              if (key && key in buckets) {
                buckets[key]++;
              }
            }

            chartData = Object.entries(buckets).map(([dateStr, count]) => ({
              d: dayNames[new Date(dateStr).getDay()],
              v: count,
            }));

            const thisWeekTotal = Object.values(buckets).reduce((s, v) => s + v, 0);
            const vals = Object.values(buckets);
            const firstHalf = vals.slice(0, 3).reduce((s, v) => s + v, 0);
            const secondHalf = vals.slice(4).reduce((s, v) => s + v, 0);
            apiChange = firstHalf > 0 ? Math.round(((secondHalf - firstHalf) / firstHalf) * 100) : 0;
            apiUsage = thisWeekTotal || toolCalls;

            // Recent queries
            const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000;
            recentQueries = activities
              .filter(a => a.query && new Date(a.created_at).getTime() > oneDayAgo)
              .slice(0, 3)
              .map(a => ({
                q: a.query!,
                t: formatTimeAgo(a.created_at),
              }));
          }
        }

        setStats({
          repos,
          papers,
          searches,
          toolCalls,
          apiUsage,
          apiChange,
          chartData,
          recentQueries,
        });
      } catch (error) {
        console.error('Failed to fetch stats:', error);
      }
    }
    fetchStats();
  }, []);
  
  function formatTimeAgo(dateStr: string): string {
    const diff = Date.now() - new Date(dateStr).getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    if (hours < 1) return 'now';
    if (hours < 24) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  }

  return (
    <PageShell>
      {/* header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-medium lowercase">overview</h1>
            <span className="px-2 py-0.5 rounded bg-[#efe7dd] text-[10px] text-[#8a7a72] uppercase tracking-wider">personal</span>
          </div>
          <p className="text-sm text-[#8a7a72] lowercase">welcome back</p>
        </div>
      </div>

      {/* user info card */}
      {profile && (
        <div className="mb-6 p-6 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <div className="flex items-center gap-4">
            {profile.avatar_url && (
              <img
                src={profile.avatar_url}
                alt=""
                className="w-10 h-10 rounded-full"
              />
            )}
            <div>
              <p className="text-sm text-[#2e2522] font-medium">
                {profile.name || profile.github_username || profile.email || "User"}
              </p>
              {profile.github_username && (
                <p className="text-xs text-[#8a7a72]">@{profile.github_username}</p>
              )}
            </div>
            <div className="ml-auto">
              <span className="px-3 py-1 rounded text-xs uppercase font-medium bg-green-500/10 text-green-400 border border-green-500/20">
                self-hosted
              </span>
            </div>
          </div>
        </div>
      )}

      {/* context stats */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs text-[#8a7a72] font-medium uppercase tracking-wider">your context</h2>
          <span className="text-xs text-[#a09488] lowercase">last 7 days</span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          <Link href="/repositories" className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf] hover:border-[#c5b5a5] transition-colors group">
            <p className="text-[11px] text-[#b58a73] uppercase tracking-wider mb-2 group-hover:text-[#ff8c3a] transition-colors">repos indexed</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.repos}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">code repositories</p>
          </Link>
          <Link href="/papers" className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf] hover:border-[#c5b5a5] transition-colors group">
            <p className="text-[11px] text-[#b58a73] uppercase tracking-wider mb-2 group-hover:text-[#ff8c3a] transition-colors">papers indexed</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.papers}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">research papers</p>
          </Link>
          <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
            <p className="text-[11px] text-[#b58a73] uppercase tracking-wider mb-2">searches</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.searches}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">code &amp; paper searches</p>
          </div>
          <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
            <p className="text-[11px] text-[#b58a73] uppercase tracking-wider mb-2">tool calls</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.toolCalls}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">total mcp requests</p>
          </div>
        </div>
      </div>

      {/* api usage + recent queries */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        {/* api usage */}
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs text-[#b58a73] font-medium uppercase tracking-wider">api usage</h3>
            <div className="flex items-center gap-2">
              <span className="text-2xl font-semibold tabular-nums">{stats.apiUsage}</span>
              {stats.apiChange > 0 && (
                <span className="text-xs text-green-500 font-medium">+{stats.apiChange}%</span>
              )}
            </div>
          </div>
          <div className="h-28 mt-2">
            {stats.chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={stats.chartData}>
                  <defs>
                    <linearGradient id="usageGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#22d3ee" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis 
                    dataKey="d" 
                    tick={{ fontSize: 10, fill: '#333' }} 
                    axisLine={false} 
                    tickLine={false}
                    dy={5}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="v" 
                    stroke="#22d3ee" 
                    fill="url(#usageGradient)" 
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={[
                  { d: 'mon', v: 0 }, { d: 'tue', v: 0 }, { d: 'wed', v: 0 },
                  { d: 'thu', v: 0 }, { d: 'fri', v: 0 }, { d: 'sat', v: 0 }, { d: 'sun', v: 0 },
                ]}>
                  <defs>
                    <linearGradient id="usageGradientEmpty" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#333" stopOpacity={0.1} />
                      <stop offset="100%" stopColor="#333" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis 
                    dataKey="d" 
                    tick={{ fontSize: 10, fill: '#333' }} 
                    axisLine={false} 
                    tickLine={false}
                    dy={5}
                  />
                  <Area 
                    type="monotone" 
                    dataKey="v" 
                    stroke="#222" 
                    fill="url(#usageGradientEmpty)" 
                    strokeWidth={1.5}
                    strokeDasharray="4 4"
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* recent queries */}
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs text-[#b58a73] font-medium uppercase tracking-wider">recent queries</h3>
            <Link 
              href="/activity" 
              className="text-xs text-[#a09488] hover:text-[#2e2522] flex items-center gap-1 lowercase transition-colors"
            >
              view all <ArrowRight size={10} />
            </Link>
          </div>
          {stats.recentQueries.length > 0 ? (
            <div className="space-y-1">
              {stats.recentQueries.map((q, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-[#efe7dd] transition-colors group cursor-pointer">
                  <div className="w-1.5 h-1.5 rounded-full bg-[#b58a73] flex-shrink-0" />
                  <p className="text-xs text-[#2e2522]/70 group-hover:text-[#2e2522] font-mono truncate flex-1 lowercase transition-colors">
                    {q.q}
                  </p>
                  <span className="text-[10px] text-[#a09488] flex-shrink-0">{q.t}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center">
              <p className="text-xs text-[#a09488] lowercase">no recent queries</p>
            </div>
          )}
        </div>
      </div>
    </PageShell>
  );
}
