"use client";

import { useEffect, useState } from "react";

/* GitHub star count for the footer, shown only once it has loaded. */
export function Stars({ repo }: { repo: string }) {
  const [stars, setStars] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`https://api.github.com/repos/${repo}`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((data: { stargazers_count?: number } | null) => {
        if (typeof data?.stargazers_count !== "number") return;
        setStars(new Intl.NumberFormat("en", { notation: "compact", compactDisplay: "short" }).format(data.stargazers_count));
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [repo]);
  return stars ? <span> [{stars}]</span> : null;
}
