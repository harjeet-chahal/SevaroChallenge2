"use client";

import { createContext, useCallback, useContext, useState } from "react";

import { useSystemStatus } from "@/components/status/system-status-provider";
import { useKeyedResource, type KeyedResource } from "@/hooks/use-keyed-resource";
import { workflowApi } from "@/lib/api/endpoints";
import type { DemoUserRole, InterventionPage, InterventionType } from "@/lib/api/types";

export interface ComposerRequest {
  type: InterventionType;
  alertId?: string | null;
  physicianIds?: string[];
  hospitalIds?: string[];
  consultId?: string | null;
  /** Changes on every "open" so re-opening re-runs the server preview. */
  nonce: number;
}

interface WorkflowContextValue {
  role: DemoUserRole;
  /** workflow version | data version | simulation time — any change refetches. */
  versionKey: string | null;
  interventions: KeyedResource<InterventionPage>;
  selectedId: string | null;
  select: (id: string | null) => void;
  composer: ComposerRequest | null;
  openComposer: (request: Omit<ComposerRequest, "nonce">) => void;
  closeComposer: () => void;
}

const WorkflowContext = createContext<WorkflowContextValue | null>(null);

/**
 * Intervention workflow state for one simulated role. Everything is read from the backend
 * and refetched whenever the workflow version, data version or simulation time changes
 * (pushed over /api/live, with polling as a fallback).
 */
export function WorkflowProvider({
  role,
  children,
}: {
  role: DemoUserRole;
  children: React.ReactNode;
}) {
  const { config } = useSystemStatus();
  const versionKey = config?.dataset_loaded
    ? `${config.workflow_version}|${config.data_version}|${config.simulation_time}`
    : null;
  const interventions = useKeyedResource(versionKey, (signal) => workflowApi.list(role, signal));
  const [selectedId, select] = useState<string | null>(null);
  const [composer, setComposer] = useState<ComposerRequest | null>(null);

  const openComposer = useCallback((request: Omit<ComposerRequest, "nonce">) => {
    setComposer({ ...request, nonce: Date.now() });
    requestAnimationFrame(() =>
      document
        .getElementById("intervention-composer")
        ?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }, []);

  return (
    <WorkflowContext
      value={{
        role,
        versionKey,
        interventions,
        selectedId,
        select,
        composer,
        openComposer,
        closeComposer: () => setComposer(null),
      }}
    >
      {children}
    </WorkflowContext>
  );
}

export function useWorkflow(): WorkflowContextValue {
  const context = useContext(WorkflowContext);
  if (!context) throw new Error("useWorkflow must be used inside <WorkflowProvider>");
  return context;
}

/** The workflow context if present (components shared with pages that have none). */
export function useOptionalWorkflow(): WorkflowContextValue | null {
  return useContext(WorkflowContext);
}
