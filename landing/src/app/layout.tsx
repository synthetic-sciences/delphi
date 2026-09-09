import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import Script from "next/script";
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

export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfaf7" },
    { media: "(prefers-color-scheme: dark)", color: "#0c0c0c" },
  ],
};

// Applies the saved or system color theme before first paint.
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("delphi-theme");if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={cmu.variable} suppressHydrationWarning>
      <body>
        <Script id="delphi-theme" strategy="beforeInteractive">
          {THEME_SCRIPT}
        </Script>
        {children}
      </body>
    </html>
  );
}
