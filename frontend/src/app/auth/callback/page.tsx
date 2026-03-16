"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { setAccessToken } from "@/lib/api";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const token = searchParams.get("token");
    if (token) {
      setAccessToken(token);
      router.replace("/overview");
    } else {
      router.replace("/?error=auth_failed");
    }
  }, [router, searchParams]);

  return (
    <div className="min-h-screen bg-[#f7f0e8] flex items-center justify-center">
      <p className="text-sm text-[#8a7a72]">Completing sign in...</p>
    </div>
  );
}
