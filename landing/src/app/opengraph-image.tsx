import { ImageResponse } from "next/og";

export const alt = "Delphi. Context before code.";
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
          padding: "72px 82px",
          background: "#111110",
          color: "#f3f3ef",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 18 }}>
          <div style={{ display: "flex", fontSize: 38, color: "#f3f3ef" }}>
            Delphi
          </div>
          <div style={{ display: "flex", fontSize: 18, color: "#8e8773" }}>
            by Synthetic Sciences
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
          <div
            style={{
              display: "flex",
              fontSize: 104,
              lineHeight: 0.98,
              letterSpacing: -2,
              color: "#f3f3ef",
              maxWidth: 920,
            }}
          >
            Context before code.
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
            Find the right source files before your coding agent answers.
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
          <div style={{ display: "flex" }}>open source / self-hosted</div>
        </div>
      </div>
    ),
    size,
  );
}
