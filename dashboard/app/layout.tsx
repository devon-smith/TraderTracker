import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Bellwether",
  description: "Prediction-market trader intelligence",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body
        style={{
          fontFamily: "ui-sans-serif, system-ui, sans-serif",
          margin: 0,
          background: "#0b0e14",
          color: "#e6e6e6",
        }}
      >
        <header
          style={{
            display: "flex",
            gap: 20,
            alignItems: "center",
            padding: "14px 24px",
            borderBottom: "1px solid #1c2230",
          }}
        >
          <strong style={{ fontSize: 18 }}>Bellwether</strong>
          <nav style={{ display: "flex", gap: 16, fontSize: 14 }}>
            <Link href="/" style={{ color: "#9bb6ff" }}>Home</Link>
            <Link href="/leaderboard" style={{ color: "#9bb6ff" }}>Leaderboard</Link>
            <Link href="/health" style={{ color: "#9bb6ff" }}>Health</Link>
          </nav>
        </header>
        <main style={{ padding: 24, maxWidth: 1100, margin: "0 auto" }}>{children}</main>
      </body>
    </html>
  );
}
