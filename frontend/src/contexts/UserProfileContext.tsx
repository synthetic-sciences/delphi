"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { getUserProfile, isAuthenticated } from "@/lib/api";

interface UserProfile {
  user_id: string;
  email: string | null;
  name: string | null;
  avatar_url: string | null;
  github_username: string | null;
  is_admin: boolean;
  tier: string;
  credits_used: number;
  credits_limit: number | null;
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

  const fetchProfile = async () => {
    try {
      setLoading(true);
      setError(null);

      // Check session first (no 401 noise in logs)
      const authed = await isAuthenticated();
      if (!authed) {
        setProfile(null);
        return;
      }

      const resp = await getUserProfile();
      if (resp.ok) {
        const data = await resp.json();
        setProfile(data);
      } else {
        setError("Failed to load profile");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProfile();
  }, []);

  return (
    <UserProfileContext.Provider value={{ profile, loading, error, refresh: fetchProfile }}>
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
