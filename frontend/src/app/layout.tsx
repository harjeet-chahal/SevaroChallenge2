import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";

import { AppShell } from "@/components/layout/app-shell";
import { THEME_INIT_SCRIPT } from "@/components/layout/theme-toggle";
import { SystemStatusProvider } from "@/components/status/system-status-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
const instrumentSerif = Instrument_Serif({ subsets: ["latin"], weight: "400", variable: "--font-instrument" });

export const metadata: Metadata = {
  title: {
    default: "NEUROGRID",
    template: "%s · NEUROGRID",
  },
  description: "Detect the disruption. Find the last safe opportunity. Engineer the rescue. Verify the recovery.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f4ef" },
    { media: "(prefers-color-scheme: dark)", color: "#0e1719" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-theme="light"
      suppressHydrationWarning
      className={cn("font-sans", geist.variable, geistMono.variable, instrumentSerif.variable)}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-dvh bg-background antialiased">
        <TooltipProvider delayDuration={200}>
          <SystemStatusProvider>
            <AppShell>{children}</AppShell>
          </SystemStatusProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
