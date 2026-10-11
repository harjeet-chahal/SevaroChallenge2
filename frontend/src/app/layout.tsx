import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";

import { AppShell } from "@/components/layout/app-shell";
import { THEME_INIT_SCRIPT } from "@/components/layout/theme-toggle";
import { SystemStatusProvider } from "@/components/status/system-status-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist-sans" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" });
const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
});

export const metadata: Metadata = {
  title: {
    default: "Sevaro Pulse",
    template: "%s · Sevaro Pulse",
  },
  description: "Tele-Neurology Operations Command Center — detect, decide, act.",
};

export const viewport: Viewport = {
  themeColor: "#f6f4ef",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-theme="light"
      suppressHydrationWarning
      className={cn(geist.variable, geistMono.variable, instrumentSerif.variable)}
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <TooltipProvider delayDuration={200}>
          <SystemStatusProvider>
            <AppShell>{children}</AppShell>
          </SystemStatusProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
