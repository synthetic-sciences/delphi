import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";

export const alt = "Delphi: a local-first context engine for coding agents";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OG() {
  const [roman, bold] = await Promise.all([
    readFile(join(process.cwd(), "public/fonts/cmu-concrete-roman.woff")),
    readFile(join(process.cwd(), "public/fonts/cmu-concrete-bold.woff")),
  ]);

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "72px 96px",
          background: "#fdfcf9",
          color: "#16150f",
          fontFamily: "CMU Concrete",
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "flex",
            fontSize: 22,
            letterSpacing: 2,
            textTransform: "uppercase",
            color: "#625d54",
          }}
        >
          Open-source software
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 128,
            fontWeight: 700,
            lineHeight: 1,
            letterSpacing: -3,
            marginTop: 28,
          }}
        >
          Delphi
        </div>
        <div
          style={{
            display: "flex",
            fontSize: 42,
            lineHeight: 1.25,
            marginTop: 26,
            maxWidth: 860,
          }}
        >
          A local-first context engine for coding agents
        </div>
        <div
          style={{
            display: "flex",
            gap: 40,
            fontSize: 24,
            color: "#625d54",
            marginTop: 54,
            paddingTop: 26,
            borderTop: "1px solid #d8d3c7",
            width: 720,
            justifyContent: "center",
          }}
        >
          <div style={{ display: "flex" }}>Synthetic Sciences</div>
          <div style={{ display: "flex" }}>trydelphi.ai</div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "CMU Concrete", data: roman, weight: 400, style: "normal" },
        { name: "CMU Concrete", data: bold, weight: 700, style: "normal" },
      ],
    },
  );
}
