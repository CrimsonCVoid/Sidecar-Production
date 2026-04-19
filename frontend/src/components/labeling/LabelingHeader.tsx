"use client";

import { ArrowLeft, FileText, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";

interface LabelingHeaderProps {
  sampleId: string;
  onSave?: () => void;
  isSaving?: boolean;
  onGeneratePdf?: () => void;
  isGeneratingPdf?: boolean;
}

export function LabelingHeader({
  sampleId,
  onSave,
  isSaving,
  onGeneratePdf,
  isGeneratingPdf,
}: LabelingHeaderProps) {
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
        onClick={onGeneratePdf}
        disabled={isGeneratingPdf}
        variant="outline"
        className="border-zinc-700 text-zinc-300 hover:text-white"
      >
        {isGeneratingPdf ? (
          <>
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            Generating...
          </>
        ) : (
          <>
            <FileText className="h-4 w-4 mr-2" />
            Generate PDF
          </>
        )}
      </Button>
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
