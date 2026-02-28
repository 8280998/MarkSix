import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Mark Six Predictor",
  description: "Hong Kong Mark Six prediction and review dashboard",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-HK">
      <body>
        <header className="topbar">
          <h1>香港六合彩预测看板</h1>
          <nav>
            <a href="/">预测</a>
            <a href="/review">复盘</a>
          </nav>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
