import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 writes AGENTS.md and CLAUDE.md into the project on `next dev`;
  // the repository keeps its agent guidance at the root instead.
  agentRules: false,
};

export default nextConfig;
