"use client";

import { use } from "react";

export default function LabelingPage({
  params,
}: {
  params: Promise<{ sampleId: string }>;
}) {
  const { sampleId } = use(params);

  return (
    <div className="flex flex-col h-screen bg-zinc-950">
      <div className="h-12 bg-zinc-900 flex items-center px-6">
        <h1 className="text-xl font-semibold">Labeling: {sampleId}</h1>
      </div>
      <div className="h-11 bg-zinc-900 border-b border-zinc-800 flex items-center px-4">
        <span className="text-sm text-zinc-400">Toolbar placeholder</span>
      </div>
      <div className="flex-1" data-testid="labeler-canvas">
        <span className="text-sm text-zinc-500 p-4 block">
          Canvas placeholder
        </span>
      </div>
    </div>
  );
}
