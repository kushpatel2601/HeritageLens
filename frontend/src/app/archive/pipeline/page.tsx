import type { Metadata } from "next";

import { PipelineDashboard } from "@/components/archive/pipeline-dashboard";

export const metadata: Metadata = {
  title: "Pipeline",
  description: "Live view of the OCR, translation, captioning and 3D reconstruction queues and the workers serving them.",
};

export default function PipelinePage() {
  return <PipelineDashboard />;
}
