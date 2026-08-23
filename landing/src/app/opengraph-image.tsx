import { ImageResponse } from "next/og";

export const alt = "Delphi. Local context for coding agents.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OG() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "84px 96px",
          background: "#0a0908",
          color: "#f4ecd6",
          fontFamily: "serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 16 }}>
          <div style={{ display: "flex", fontSize: 36, color: "#fbf5e3" }}>
            delphi
          </div>
          <div style={{ display: "flex", fontSize: 18, color: "#8e8773" }}>
            by Synthetic Sciences
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
          <div
            style={{
              display: "flex",
              fontSize: 96,
              lineHeight: 1.04,
              letterSpacing: -2,
              color: "#fbf5e3",
              maxWidth: 920,
            }}
          >
            Your agent should read the repo first.
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 32,
              lineHeight: 1.35,
              color: "#d6cdb5",
              maxWidth: 900,
            }}
          >
            Delphi searches your sources before the agent answers.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: 16,
            color: "#8e8773",
          }}
        >
          <div style={{ display: "flex" }}>
            trydelphi.ai
          </div>
          <div style={{ display: "flex" }}>open source · self-hosted</div>
        </div>
      </div>
    ),
    size,
  );
}
