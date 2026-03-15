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

// Tier color mapping
function getTierColor(tier: string) {
  switch (tier) {
    case "lab": return "bg-purple-500/10 text-purple-400 border border-purple-500/20";
    case "researcher": return "bg-blue-500/10 text-blue-400 border border-blue-500/20";
    default: return "bg-[#1a1a1a] text-[#666]";
  }
}

// Credit status color (red when high usage)
function getCreditColor(percentUsed: number) {
  if (percentUsed >= 90) return "text-red-500";
  if (percentUsed >= 70) return "text-orange-500";
  if (percentUsed >= 50) return "text-yellow-500";
  return "text-green-500";
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
            <span className="px-2 py-0.5 rounded bg-[#111] text-[10px] text-[#555] uppercase tracking-wider">personal</span>
            {profile && (
              <span className={`px-2 py-0.5 rounded text-[10px] uppercase ${getTierColor(profile.tier)}`}>
                {profile.tier}
              </span>
            )}
          </div>
          <p className="text-sm text-[#555] lowercase">welcome back</p>
        </div>
      </div>

      {/* credit usage card */}
      {profile && (
        <div className="mb-6 p-6 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-xs text-[#fa7315] font-medium uppercase tracking-wider mb-2">subscription</h2>
              <div className="flex items-center gap-3">
                <span className={`px-3 py-1 rounded text-sm uppercase font-medium ${getTierColor(profile.tier)}`}>
                  {profile.tier}
                </span>
                {profile.github_username && (
                  <span className="text-sm text-[#555]">@{profile.github_username}</span>
                )}
              </div>
            </div>
            <div className="text-right">
              <p className="text-xs text-[#555] uppercase tracking-wider mb-1">
                {profile.tier === 'free' ? 'credits (lifetime)' : 'credits this month'}
              </p>
              <p className={`text-2xl font-semibold tabular-nums ${getCreditColor(profile.credits_percent_used)}`}>
                {profile.credits_used} <span className="text-lg text-[#555]">/ {profile.credits_limit}</span>
              </p>
              <p className="text-xs text-[#444] mt-0.5">${profile.cost_usd_used.toFixed(4)} used</p>
            </div>
          </div>

          {/* Progress bar */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-[#555] uppercase tracking-wider">usage</span>
              <span className={`text-xs font-mono font-medium ${getCreditColor(profile.credits_percent_used)}`}>
                {profile.credits_percent_used.toFixed(1)}%
              </span>
            </div>
            <div className="h-2 bg-[#111] rounded-full overflow-hidden">
              <div
                className={`h-full ${getCreditColor(profile.credits_percent_used)} bg-current transition-all`}
                style={{ width: `${Math.min(100, profile.credits_percent_used)}%` }}
              />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-[#444]">
                {profile.credits_available.toFixed(2)} credits {profile.tier === 'free' ? 'remaining' : 'left this month'}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* context stats */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-xs text-[#555] font-medium uppercase tracking-wider">your context</h2>
          <span className="text-xs text-[#333] lowercase">last 7 days</span>
        </div>
        <div className="grid grid-cols-4 gap-3">
          <Link href="/repositories" className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] hover:border-[#2a2a2a] transition-colors group">
            <p className="text-[11px] text-[#fa7315] uppercase tracking-wider mb-2 group-hover:text-[#ff8c3a] transition-colors">repos indexed</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.repos}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">code repositories</p>
          </Link>
          <Link href="/papers" className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a] hover:border-[#2a2a2a] transition-colors group">
            <p className="text-[11px] text-[#fa7315] uppercase tracking-wider mb-2 group-hover:text-[#ff8c3a] transition-colors">papers indexed</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.papers}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">research papers</p>
          </Link>
          <div className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
            <p className="text-[11px] text-[#fa7315] uppercase tracking-wider mb-2">searches</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.searches}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">code &amp; paper searches</p>
          </div>
          <div className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
            <p className="text-[11px] text-[#fa7315] uppercase tracking-wider mb-2">tool calls</p>
            <p className="text-2xl font-semibold tabular-nums">{stats.toolCalls}</p>
            <p className="text-[10px] text-[#22d3ee]/50 mt-1.5 lowercase">total mcp requests</p>
          </div>
        </div>
      </div>

      {/* api usage + recent queries */}
      <div className="grid grid-cols-2 gap-4 mb-6">
        {/* api usage */}
        <div className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs text-[#fa7315] font-medium uppercase tracking-wider">api usage</h3>
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
        <div className="p-4 rounded-xl bg-[#0f0f0f] border border-[#1a1a1a]">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs text-[#fa7315] font-medium uppercase tracking-wider">recent queries</h3>
            <Link 
              href="/activity" 
              className="text-xs text-[#444] hover:text-white flex items-center gap-1 lowercase transition-colors"
            >
              view all <ArrowRight size={10} />
            </Link>
          </div>
          {stats.recentQueries.length > 0 ? (
            <div className="space-y-1">
              {stats.recentQueries.map((q, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 rounded-lg hover:bg-[#111] transition-colors group cursor-pointer">
                  <div className="w-1.5 h-1.5 rounded-full bg-[#fa7315] flex-shrink-0" />
                  <p className="text-xs text-white/70 group-hover:text-white font-mono truncate flex-1 lowercase transition-colors">
                    {q.q}
                  </p>
                  <span className="text-[10px] text-[#333] flex-shrink-0">{q.t}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center">
              <p className="text-xs text-[#333] lowercase">no recent queries</p>
            </div>
          )}
        </div>
      </div>
    </PageShell>
  );
}
