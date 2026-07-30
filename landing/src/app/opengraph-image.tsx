import { ImageResponse } from "next/og";

export const alt =
  "Delphi. The context engine for agents that have to get the code right.";
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
        <div
          style={{
            display: "flex",
            fontSize: 17,
            color: "#8e8773",
            fontStyle: "italic",
          }}
        >
          A Synthetic Sciences project
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 36 }}>
          <div
            style={{
              display: "flex",
              fontSize: 168,
              lineHeight: 1,
              letterSpacing: -3,
              color: "#fbf5e3",
            }}
          >
            Delphi.
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
            The context engine for agents that have to get the code right.
            Open source, self-hosted, and built by Synthetic Sciences.
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
          <div style={{ display: "flex" }}>
            0.528 recall@20 · 6.5x faster · self-hosted
          </div>
        </div>
      </div>
    ),
    size,
  );
}
