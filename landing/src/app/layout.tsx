import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

const cmu = localFont({
  variable: "--font-cmu",
  display: "swap",
  src: [
    { path: "../../public/fonts/cmu-concrete-roman.woff", weight: "400", style: "normal" },
    { path: "../../public/fonts/cmu-concrete-bold.woff", weight: "700", style: "normal" },
  ],
});

const TITLE = "Delphi: a local-first context engine for coding agents";
const DESCRIPTION =
  "Delphi indexes repositories, documentation, papers, and datasets on your own machine and serves search, code structure, and context packs to coding agents over MCP. Open source, Apache 2.0.";

export const metadata: Metadata = {
  metadataBase: new URL("https://trydelphi.ai"),
  title: {
    default: TITLE,
    template: "%s",
  },
  description: DESCRIPTION,
  openGraph: {
    title: TITLE,
    description: DESCRIPTION,
    type: "website",
    url: "https://trydelphi.ai",
    siteName: "Delphi",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
  robots: {
    index: true,
    follow: true,
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={cmu.variable}>
      <body>{children}</body>
    </html>
  );
}
