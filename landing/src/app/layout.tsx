import type { Metadata } from "next";
import { Source_Serif_4, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const serif = Source_Serif_4({
  variable: "--font-serif",
  subsets: ["latin"],
  display: "swap",
});

const mono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://trydelphi.ai"),
  title: {
    default: "Delphi · Context for agents that have to get the code right",
    template: "%s",
  },
  description:
    "Open-source context infrastructure for agents working across code, documentation, papers, and datasets. Self-hosted and built by Synthetic Sciences.",
  openGraph: {
    title: "Delphi · Context for agents that have to get the code right",
    description:
      "Open-source context infrastructure for agents working across real software and research.",
    type: "website",
    url: "https://trydelphi.ai",
    siteName: "Delphi",
  },
  twitter: {
    card: "summary_large_image",
    title: "Delphi · Context for agents that have to get the code right",
    description:
      "Open-source context infrastructure for agents working across real software and research.",
  },
  robots: {
    index: true,
    follow: true,
  },
};

// Inline init script: read localStorage and set data-theme before React mounts,
// so first paint never flashes the wrong theme.
const THEME_INIT = `
(function(){try{
  var t=localStorage.getItem('delphi-theme');
  if(t!=='light'&&t!=='dark'){
    t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';
  }
  document.documentElement.setAttribute('data-theme',t);
}catch(e){document.documentElement.setAttribute('data-theme','dark');}})();
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${serif.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
