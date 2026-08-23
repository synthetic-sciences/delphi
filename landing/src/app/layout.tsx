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
    default: "Delphi · Local context for agents",
    template: "%s",
  },
  description:
    "Delphi searches your sources before your coding agent answers.",
  openGraph: {
    title: "Delphi · Local context for agents",
    description:
      "Search your sources before the coding agent answers.",
    type: "website",
    url: "https://trydelphi.ai",
    siteName: "Delphi",
  },
  twitter: {
    card: "summary_large_image",
    title: "Delphi · Local context for agents",
    description:
      "Search your sources before the coding agent answers.",
  },
  robots: {
    index: true,
    follow: true,
  },
};

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
