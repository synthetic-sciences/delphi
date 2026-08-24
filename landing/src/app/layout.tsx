import type { Metadata } from "next";
import localFont from "next/font/local";
import { JetBrains_Mono } from "next/font/google";
import "./globals.css";

const cmu = localFont({
  variable: "--font-cmu",
  display: "swap",
  src: [
    { path: "../../public/fonts/cmu-concrete-roman.woff", weight: "400", style: "normal" },
    { path: "../../public/fonts/cmu-concrete-bold.woff", weight: "700", style: "normal" },
  ],
});

const mono = JetBrains_Mono({
  variable: "--font-jbmono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://trydelphi.ai"),
  title: {
    default: "Delphi. The right context, before the code.",
    template: "%s",
  },
  description:
    "Delphi indexes your repos, docs, papers, and datasets, then hands your coding agent precise, cited context over MCP. Open source and local first.",
  openGraph: {
    title: "Delphi. The right context, before the code.",
    description:
      "Local search for your agent's code, docs, and papers. Open source, self-hosted, MCP native.",
    type: "website",
    url: "https://trydelphi.ai",
    siteName: "Delphi",
  },
  twitter: {
    card: "summary_large_image",
    title: "Delphi. The right context, before the code.",
    description:
      "Local search for your agent's code, docs, and papers. Open source, self-hosted, MCP native.",
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
    <html lang="en" className={`${cmu.variable} ${mono.variable}`}>
      <body className="min-h-full bg-background text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
