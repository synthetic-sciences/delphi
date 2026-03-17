"use client";

import PageShell from "@/components/PageShell";
import { useState, useEffect, useMemo } from "react";
import { 
  Search, FileDown, List, RefreshCw, BookOpen, FileText, 
  Quote, Calculator, Code, GitCompare, Network, Zap,
  Activity as ActivityIcon, Filter, Trash2
} from "lucide-react";
import { apiGet } from "@/lib/api";

// Action configuration — orange depth palette
const actionConfig: Record<string, { icon: React.ReactNode; label: string; color: string }> = {
  // Code Context
  'index_repository': { icon: <FileDown size={16} />,  label: 'Index Repo',     color: '#d06e28' },
  'delete_repository': { icon: <Trash2 size={16} />,   label: 'Delete Repo',    color: '#7a2e0c' },
  'search_code':       { icon: <Search size={16} />,   label: 'Search Code',    color: '#e08840' },
  'search_symbols':    { icon: <Code size={16} />,     label: 'Search Symbols', color: '#b85618' },
  'list_repositories': { icon: <List size={16} />,     label: 'List Repos',     color: '#9a3f10' },
  'get_file':          { icon: <FileText size={16} />, label: 'Get File',       color: '#eda868' },

  // Paper Context
  'index':       { icon: <FileDown size={16} />,  label: 'Index Paper',   color: '#d06e28' },
  'index_paper': { icon: <FileDown size={16} />,  label: 'Index Paper',   color: '#d06e28' },
  'delete_paper':{ icon: <Trash2 size={16} />,    label: 'Delete Paper',  color: '#7a2e0c' },
  'search':      { icon: <Search size={16} />,    label: 'Search',        color: '#e08840' },
  'search_papers':{ icon: <Search size={16} />,   label: 'Search Papers', color: '#e08840' },
  'list_papers': { icon: <List size={16} />,      label: 'List Papers',   color: '#9a3f10' },
  'get_paper':   { icon: <BookOpen size={16} />,  label: 'Get Paper',     color: '#eda868' },
  'report':      { icon: <FileText size={16} />,  label: 'Report',        color: '#b85618' },
  'rebuild_index':{ icon: <RefreshCw size={16} />,label: 'Rebuild Index', color: '#e08840' },
  'find_related':{ icon: <Network size={16} />,   label: 'Find Related',  color: '#c96030' },

  // Extraction
  'citations':    { icon: <Quote size={16} />,      label: 'Citations',    color: '#b85618' },
  'equations':    { icon: <Calculator size={16} />, label: 'Equations',    color: '#9a3f10' },
  'code_snippets':{ icon: <Code size={16} />,       label: 'Code Snippets',color: '#d06e28' },

  // Analysis
  'compare':        { icon: <GitCompare size={16} />, label: 'Compare',        color: '#7a2e0c' },
  'citation_graph': { icon: <Network size={16} />,    label: 'Citation Graph', color: '#c96030' },
};

interface ActivityItem {
  id: string;
  action: string;
  created_at: string;
  paper_id?: string;
  paper_title?: string;
  repo_id?: string;
  query?: string;
  results_count?: number;
  duration_ms?: number;
  details?: {
    cached?: boolean;
    response_time_ms?: number;
    error?: string;
    [key: string]: unknown;
  };
}

const timeFilters = ['24h', '7d', '30d'] as const;
type TimeFilter = typeof timeFilters[number];

const typeFilters = [
  { value: 'all', label: 'All Activities' },
  { group: 'Code', options: [
    { value: 'index_repository', label: 'Index Repository' },
    { value: 'search_code', label: 'Search Code' },
    { value: 'search_symbols', label: 'Search Symbols' },
    { value: 'list_repositories', label: 'List Repos' },
  ]},
  { group: 'Papers', options: [
    { value: 'index_paper', label: 'Index Paper' },
    { value: 'search_papers', label: 'Search Papers' },
    { value: 'list_papers', label: 'List Papers' },
    { value: 'report', label: 'Report' },
  ]},
  { group: 'Extraction', options: [
    { value: 'citations', label: 'Citations' },
    { value: 'equations', label: 'Equations' },
    { value: 'code_snippets', label: 'Code Snippets' },
  ]},
];

function formatTimeAgo(dateStr: string): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diff = now - date;
  
  const minutes = Math.floor(diff / (1000 * 60));
  const hours = Math.floor(diff / (1000 * 60 * 60));
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));
  
  if (minutes < 1) return 'now';
  if (minutes < 60) return `${minutes}m`;
  if (hours < 24) return `${hours}h`;
  if (days < 7) return `${days}d`;
  return new Date(dateStr).toLocaleDateString();
}


export default function ActivityPage() {
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [timeFilter, setTimeFilter] = useState<TimeFilter>('7d');

  // Fetch activities from backend
  useEffect(() => {
    async function fetchActivities() {
      setLoading(true);
      try {
        const { ok, data } = await apiGet<{ activities: ActivityItem[] }>(
          `/v1/activity?time_range=${timeFilter}&limit=100`
        );
        setActivities(ok && data?.activities ? data.activities : []);
      } catch (error) {
        console.error('Failed to fetch activities:', error);
        setActivities([]);
      } finally {
        setLoading(false);
      }
    }
    fetchActivities();
  }, [timeFilter]);

  // Filter activities
  const filteredActivities = useMemo(() => {
    const now = Date.now();
    const timeRanges: Record<TimeFilter, number> = {
      '24h': 24 * 60 * 60 * 1000,
      '7d': 7 * 24 * 60 * 60 * 1000,
      '30d': 30 * 24 * 60 * 60 * 1000,
    };
    const timeRange = timeRanges[timeFilter];

    return activities.filter(a => {
      // Time filter
      const activityTime = new Date(a.created_at).getTime();
      if (now - activityTime > timeRange) return false;
      
      // Type filter
      if (typeFilter !== 'all' && a.action !== typeFilter) return false;
      
      // Search filter
      if (searchQuery) {
        const query = searchQuery.toLowerCase();
        const matchesAction = a.action.toLowerCase().includes(query);
        const matchesQuery = a.query?.toLowerCase().includes(query);
        const matchesTitle = a.paper_title?.toLowerCase().includes(query);
        if (!matchesAction && !matchesQuery && !matchesTitle) return false;
      }
      
      return true;
    });
  }, [activities, timeFilter, typeFilter, searchQuery]);

  // Calculate stats
  const stats = useMemo(() => {
    const total = filteredActivities.length;
    const successful = filteredActivities.filter(a => !a.details?.error).length;
    const successRate = total > 0 ? Math.round((successful / total) * 100) : 100;
    
    const responseTimes = filteredActivities
      .map(a => a.duration_ms || a.details?.response_time_ms)
      .filter((t): t is number => t !== undefined && t !== null);
    const avgResponseTime = responseTimes.length > 0 
      ? responseTimes.reduce((sum, t) => sum + t, 0) / responseTimes.length / 1000 
      : 0;

    return { total, successRate, avgResponseTime };
  }, [filteredActivities]);

  return (
    <PageShell>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium lowercase mb-1">activity</h1>
          <p className="text-sm text-[#8a7a72] lowercase">track your api usage and tool calls</p>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">total queries</p>
          <p className="text-2xl font-semibold tabular-nums">{stats.total}</p>
        </div>
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">success rate</p>
          <p className="text-2xl font-semibold tabular-nums">{stats.successRate}<span className="text-sm text-[#8a7a72]">%</span></p>
        </div>
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">avg response</p>
          <p className="text-2xl font-semibold tabular-nums">{stats.avgResponseTime.toFixed(1)}<span className="text-sm text-[#8a7a72]">s</span></p>
        </div>
        <div className="p-4 rounded-xl bg-[#faf5ef] border border-[#dfcdbf]">
          <p className="text-[11px] text-[#8a7a72] uppercase tracking-wider mb-1">period</p>
          <p className="text-2xl font-semibold tabular-nums">{timeFilter.replace('h', '').replace('d', '')}<span className="text-sm text-[#8a7a72]">{timeFilter.includes('h') ? 'h' : 'd'}</span></p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        {/* Search */}
        <div className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#a09488]" />
          <input 
            type="text" 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="search activity..." 
            className="w-full h-10 pl-9 pr-4 rounded-lg bg-[#faf5ef] border border-[#dfcdbf] text-sm text-[#2e2522] placeholder-[#a09488] focus:outline-none focus:border-[#c5b5a5] lowercase transition-colors" 
          />
        </div>

        {/* Type Filter */}
        <div className="relative">
          <Filter size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#a09488] pointer-events-none" />
          <select 
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="h-10 pl-9 pr-8 rounded-lg bg-[#faf5ef] border border-[#dfcdbf] text-sm text-[#2e2522] focus:outline-none focus:border-[#c5b5a5] lowercase appearance-none cursor-pointer transition-colors"
          >
            {typeFilters.map((item, i) => (
              'value' in item ? (
                <option key={i} value={item.value}>{item.label}</option>
              ) : (
                <optgroup key={i} label={item.group}>
                  {item.options.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </optgroup>
              )
            ))}
          </select>
        </div>

        {/* Time Filter */}
        <div className="flex items-center gap-1 p-1 rounded-lg bg-[#faf5ef] border border-[#dfcdbf]">
          {timeFilters.map((t) => (
            <button
              key={t}
              onClick={() => setTimeFilter(t)}
              className={`px-3 py-1.5 rounded text-xs lowercase transition-colors ${
                timeFilter === t 
                  ? 'bg-[#b58a73] text-black font-medium' 
                  : 'text-[#8a7a72] hover:text-[#2e2522]'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Activity List */}
      <div className="rounded-xl bg-[#faf5ef] border border-[#dfcdbf] overflow-hidden">
        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw size={24} className="text-[#a09488] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#a09488] lowercase">loading activity...</p>
          </div>
        ) : filteredActivities.length === 0 ? (
          <div className="p-12 text-center">
            <ActivityIcon size={32} className="text-[#c5b5a5] mx-auto mb-3" />
            <h3 className="text-sm text-[#8a7a72] lowercase mb-1">no activity yet</h3>
            <p className="text-xs text-[#a09488] lowercase">your api usage will appear here once you start making requests.</p>
          </div>
        ) : (
          <div className="divide-y divide-[#dfcdbf]">
            {filteredActivities.map((activity) => {
              const config = actionConfig[activity.action] || { 
                icon: <Zap size={16} />, 
                label: activity.action, 
                color: '#6b7280' 
              };
              const isCached = activity.details?.cached;
              const subtitle = activity.query || activity.paper_title || (activity.details?.repo_name as string) || 'API request';
              
              return (
                <div 
                  key={activity.id} 
                  className="flex items-center gap-4 px-4 py-3 hover:bg-[#efe7dd] transition-colors cursor-pointer group"
                >
                  {/* Icon */}
                  <div 
                    className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
                    style={{ backgroundColor: `${config.color}20`, color: config.color }}
                  >
                    {config.icon}
                  </div>
                  
                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-0.5">
                      <span className="text-sm font-medium text-[#2e2522]">{config.label}</span>
                      {isCached && (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase tracking-wider bg-[#faebd5] text-[#b85618]">
                          cached
                        </span>
                      )}
                      {activity.results_count !== undefined && (
                        <span className="text-[10px] text-[#a09488]">
                          {activity.results_count} results
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[#8a7a72] truncate lowercase">{subtitle}</p>
                  </div>
                  
                  {/* Duration */}
                  {(activity.duration_ms || activity.details?.response_time_ms) && (
                    <span className="text-[10px] text-[#a09488] tabular-nums flex-shrink-0">
                      {((activity.duration_ms || activity.details?.response_time_ms || 0) / 1000).toFixed(2)}s
                    </span>
                  )}
                  
                  {/* Time */}
                  <span className="text-xs text-[#a09488] flex-shrink-0 w-12 text-right">
                    {formatTimeAgo(activity.created_at)}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </PageShell>
  );
}
