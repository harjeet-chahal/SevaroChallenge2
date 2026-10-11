import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { LiveReadout } from "@/components/landing/live-readout";
import { LoopStepper } from "@/components/landing/loop-stepper";
import { RoleCards } from "@/components/landing/role-cards";
import { EYEBROW } from "@/components/shared/page-header";

export default function Home() {
  return (
    <div className="flex flex-col gap-[72px] pt-4 min-[900px]:pt-8">
      <section className="grid items-center gap-10 min-[1200px]:grid-cols-[7fr_5fr]">
        <div className="space-y-6">
          <p className={EYEBROW}>Tele-neurology operations command center</p>
          <h1 className="font-serif text-[clamp(40px,4vw,56px)] leading-[1.04] font-normal tracking-[-0.02em] text-balance text-foreground">
            Detect coverage risk. Decide with the evidence.{" "}
            <em className="text-primary">Act before the gap opens.</em>
          </h1>
          <p className="max-w-[620px] text-body text-foreground-2">
            Sevaro Pulse reduces manual coordination work by 80%. The intelligent system predicts staffing shortages up to 90 minutes in advance and has potential to impact 800K Americans who suffer a stroke every year.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Link
              href="/coordinator"
              className="inline-flex h-11 items-center gap-2 rounded-full border border-primary bg-primary px-[18px] text-sm font-semibold text-primary-foreground hover:bg-primary/85"
            >
              Open the command center
              <ArrowRight className="size-4" aria-hidden />
            </Link>
            <Link
              href="/clinical-lead"
              className="inline-flex h-11 items-center gap-2 rounded-full border border-border-strong px-[18px] text-sm font-semibold text-foreground hover:border-primary"
            >
              Review approvals
            </Link>
          </div>
        </div>
        <LiveReadout />
      </section>

      <section aria-labelledby="roles-heading" className="space-y-5">
        <div className="space-y-1.5">
          <p className={EYEBROW}>Choose a role</p>
          <h2 id="roles-heading" className="font-serif text-[34px] leading-[1.05] tracking-[-0.01em]">
            Three people, one rescue.
          </h2>
        </div>
        <RoleCards />
      </section>

      <section
        aria-labelledby="loop-heading"
        className="grid items-start gap-8 min-[1200px]:grid-cols-[5fr_7fr]"
      >
        <div className="space-y-4">
          <p className={EYEBROW}>How it works</p>
          <h2
            id="loop-heading"
            className="font-serif text-[clamp(34px,3.4vw,46px)] leading-[1.05] tracking-[-0.02em]"
          >
            A human-approved loop that <em className="text-primary">keeps coverage whole.</em>
          </h2>
          <p className="max-w-[520px] text-body text-foreground-2">
            Nothing reaches an off-shift physician until a clinical lead approves it. All data is
            synthetic or from the challenge dataset; no real SMS, email or hospital integration
            exists.
          </p>
        </div>
        <LoopStepper />
      </section>
    </div>
  );
}
