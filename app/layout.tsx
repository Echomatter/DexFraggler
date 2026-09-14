import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DexFraggler — FM waveform laboratory",
  description: "Fit saw, square and triangle waveforms to a six-operator DX7 core.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
