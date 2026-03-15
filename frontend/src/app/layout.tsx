import type { Metadata } from "next";
import "./globals.css";
import { UserProfileProvider } from "@/contexts/UserProfileContext";

export const metadata: Metadata = {
  title: "Synthetic Sciences",
  description: "Synthetic Sciences Dashboard",
  icons: {
    icon: "/icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <UserProfileProvider>
          {children}
        </UserProfileProvider>
      </body>
    </html>
  );
}
