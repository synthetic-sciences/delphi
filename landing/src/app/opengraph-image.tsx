import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { ImageResponse } from "next/og";

export const alt = "Delphi. The right context, before the code.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function OG() {
  const cmu = await readFile(
    join(process.cwd(), "public/fonts/cmu-concrete-roman.woff"),
  );

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "64px 78px",
          background: "#141110",
          color: "#ede7d7",
          fontFamily: "CMU Concrete",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
          }}
        >
          <div style={{ display: "flex", fontSize: 40 }}>delphi</div>
          <div style={{ display: "flex", fontSize: 20, color: "#9b8f74" }}>
            by Synthetic Sciences
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 30 }}>
          <div
            style={{
              display: "flex",
              fontSize: 100,
              lineHeight: 1.02,
              letterSpacing: -2.4,
              maxWidth: 980,
            }}
          >
            The right context, before the code.
          </div>
          <div
            style={{
              display: "flex",
              fontSize: 30,
              lineHeight: 1.4,
              color: "#c9bda0",
              maxWidth: 900,
            }}
          >
            Local search for your agent&apos;s code, docs, and papers.
          </div>
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: 19,
            color: "#9b8f74",
            borderTop: "1px solid #2e2921",
            paddingTop: 28,
          }}
        >
          <div style={{ display: "flex" }}>$ npx @synsci/delphi</div>
          <div style={{ display: "flex" }}>trydelphi.ai</div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        {
          name: "CMU Concrete",
          data: cmu,
          weight: 400,
          style: "normal",
        },
      ],
    },
  );
}
