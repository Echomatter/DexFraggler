import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DexFraggler — DX7 wavetable map",
  description: "Anchor a waveform path across 32 slices and solve it through all 32 DX7 algorithms.",
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
