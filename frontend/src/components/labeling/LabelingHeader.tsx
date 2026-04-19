"use client";

import { ArrowLeft } from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

interface LabelingHeaderProps {
  sampleId: string;
  onSave?: () => void;
  isSaving?: boolean;
}

export function LabelingHeader({ sampleId, onSave, isSaving }: LabelingHeaderProps) {
  const router = useRouter();

  return (
    <div className="h-12 bg-zinc-900 flex items-center px-6 gap-4 shrink-0">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => router.push("/")}
        aria-label="Back to dashboard"
      >
        <ArrowLeft className="h-5 w-5" />
      </Button>
      <h1 className="text-xl font-semibold text-white">
        Labeling: {sampleId}
      </h1>
      <div className="flex-1" />
      <Button
        onClick={onSave}
        disabled={isSaving}
        className="bg-blue-500 hover:bg-blue-600 text-white"
      >
        {isSaving ? "Saving..." : "Save Labels"}
      </Button>
    </div>
  );
}
