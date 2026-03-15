"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { apiGet } from "@/lib/api";

interface UserProfile {
  user_id: string;
  tier: "free" | "researcher" | "lab";
  credits_limit: number;
  credits_used: number;
  credits_available: number;
  credits_percent_used: number;
  cost_usd_used: number;
  github_id: number | null;
  github_username: string | null;
}

interface UserProfileContextValue {
  profile: UserProfile | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

const UserProfileContext = createContext<UserProfileContextValue | undefined>(undefined);

export function UserProfileProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProfile = async (forceRefresh: boolean = false) => {
    try {
      setLoading(true);
      setError(null);
      // Force refresh on app load to ensure tier upgrades are immediate
      const endpoint = forceRefresh ? "/v1/user/profile?force_refresh=true" : "/v1/user/profile";
      const result = await apiGet<{ success: boolean; profile: UserProfile }>(endpoint);

      if (result.ok && result.data?.success) {
        setProfile(result.data.profile);
      } else {
        setError(result.error || "Failed to load profile");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Always force refresh on mount (user just logged in/opened app)
    fetchProfile(true);
  }, []);

  return (
    <UserProfileContext.Provider value={{ profile, loading, error, refresh: () => fetchProfile(true) }}>
      {children}
    </UserProfileContext.Provider>
  );
}

export function useUserProfile() {
  const context = useContext(UserProfileContext);
  if (!context) {
    throw new Error("useUserProfile must be used within UserProfileProvider");
  }
  return context;
}
