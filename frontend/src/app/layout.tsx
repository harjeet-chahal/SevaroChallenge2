import type { Metadata, Viewport } from "next";
import { Geist } from "next/font/google";

import { AppHeader } from "@/components/layout/app-header";
import { SystemStatusProvider } from "@/components/status/system-status-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });

export const metadata: Metadata = {
  title: {
    default: "Sevaro Pulse",
    template: "%s · Sevaro Pulse",
  },
  description: "Tele-Neurology Operations Command Center — detect, decide, act.",
};

export const viewport: Viewport = {
  themeColor: "#13294b",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={cn("font-sans", geist.variable)}>
      <body className="min-h-dvh bg-background antialiased">
        <TooltipProvider delayDuration={200}>
          <SystemStatusProvider>
            <AppHeader />
            <main className="mx-auto w-full max-w-screen-2xl px-4 py-6 sm:px-6 lg:px-8">
              {children}
            </main>
          </SystemStatusProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
