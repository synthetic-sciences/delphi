"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AuthCallbackPage() {
  const router = useRouter();

  useEffect(() => {
    // Session cookie was set by the backend redirect — just navigate to app.
    router.replace("/overview");
  }, [router]);

  return (
    <div className="min-h-screen bg-[#f7f0e8] flex items-center justify-center">
      <p className="text-sm text-[#8a7a72]">Completing sign in...</p>
    </div>
  );
}
