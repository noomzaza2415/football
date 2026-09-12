import type { Metadata } from "next";
import Link from "next/link";

import { DisclaimerFootnote } from "@/components/Disclaimer";

import "./globals.css";

export const metadata: Metadata = {
  title: "วิเคราะห์สูง/ต่ำ",
  description:
    "โมเดล Poisson สำหรับวิเคราะห์ตลาดสูง/ต่ำในฟุตบอล เป็นเครื่องมือทางสถิติเพื่อการศึกษาเท่านั้น",
};

const NAV_LINKS = [
  { href: "/", label: "โปรแกรมแข่ง" },
  { href: "/performance", label: "ผลงานโมเดล" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <body className="min-h-screen bg-plane text-ink antialiased">
        <div className="mx-auto flex min-h-screen max-w-6xl flex-col px-4 py-6 sm:px-6 lg:px-8">
          <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <Link href="/" className="group flex items-center gap-3">
              <span
                aria-hidden="true"
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-series-1/15 text-lg ring-1 ring-series-1/30"
              >
                ⚽
              </span>
              <span>
                <span className="block text-base font-semibold tracking-tight text-ink">
                  วิเคราะห์สูง/ต่ำ
                </span>
                <span className="block text-xs text-ink-muted">
                  โมเดล Poisson ทำนายจำนวนประตู
                </span>
              </span>
            </Link>

            <nav aria-label="เมนูหลัก">
              <ul className="flex items-center gap-1">
                {NAV_LINKS.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="rounded-lg px-3 py-2 text-sm font-medium text-ink-secondary transition-colors hover:bg-surface hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-series-1"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </header>

          <main className="flex-1">{children}</main>

          <footer className="mt-12 border-t border-hairline pt-6">
            <DisclaimerFootnote />
            <p className="mt-2 text-xs text-ink-muted">
              สร้างขึ้นเพื่อศึกษาว่าโมเดล Poisson ให้ผลต่างจากราคาที่ตลาดเปิดไว้อย่างไร
            </p>
          </footer>
        </div>
      </body>
    </html>
  );
}
