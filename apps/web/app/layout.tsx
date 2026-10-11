import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

/*
 * THESIS: an instrument for reading agent runs; the waterfall and the failing
 * span are the product, everything else gets out of the way. Refuses the neon
 * "AI dashboard" with glowing cards and hero metrics.
 * OWN-WORLD: graphite neutrals, signal amber only for action/selection/focus,
 * green/red reserved for status, Geist for UI and Geist Mono strictly for data.
 * STORY: an engineer finds the failing trace, sees which span broke and why,
 * and fixes it; setup takes one key and one snippet.
 * FIRST VIEWPORT (landing): headline and the real install path on the left, a
 * labeled synthetic trace waterfall with one failing tool span on the right.
 * FORM: brief-pinned (owner chose "precision instrument" + amber).
 */

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "TraceLens", template: "%s · TraceLens" },
  description: "Open-source tracing, failure investigation, and evaluations for AI agents.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
