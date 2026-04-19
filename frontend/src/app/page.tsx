"use client";

import useSWR from "swr";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { FileText, ArrowRight } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Sample {
  id: string;
  address: string;
  panel_count: number;
  latest_run_status: string | null;
  latest_run_progress: number | null;
  latest_run_started: string | null;
  latest_run_completed: string | null;
  pdf_path: string | null;
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

function StatusBadge({ status }: { status: string | null }) {
  if (!status) {
    return <Badge variant="outline" className="text-zinc-500">No runs</Badge>;
  }
  const map: Record<string, { className: string; label: string }> = {
    queued: { className: "bg-zinc-700 text-zinc-200", label: "Queued" },
    running: { className: "bg-yellow-900 text-yellow-300", label: "Running" },
    done: { className: "bg-green-900 text-green-300", label: "Complete" },
    error: { className: "bg-red-900 text-red-300", label: "Failed" },
  };
  const s = map[status] ?? { className: "bg-zinc-700 text-zinc-200", label: status };
  return <Badge className={s.className}>{s.label}</Badge>;
}

export default function DashboardPage() {
  const { data: samples, error, isLoading } = useSWR<Sample[]>(
    `${API_BASE}/api/pipeline/samples`,
    fetcher,
    { refreshInterval: 3000 },
  );

  return (
    <div className="min-h-screen bg-zinc-950 p-6">
      <div className="max-w-5xl mx-auto">
        <h1 className="text-2xl font-semibold text-white mb-1">
          My Metal Roofer
        </h1>
        <p className="text-zinc-400 mb-6">Roof samples dashboard</p>

        {isLoading && (
          <div className="text-zinc-500 py-12 text-center">
            Loading samples...
          </div>
        )}

        {error && (
          <div className="text-red-400 py-12 text-center">
            Failed to load samples. Is the API running at {API_BASE}?
          </div>
        )}

        {samples && samples.length === 0 && (
          <div className="text-zinc-500 py-12 text-center">
            No samples found. Create samples in Supabase to get started.
          </div>
        )}

        {samples && samples.length > 0 && (
          <div className="border border-zinc-800 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-900/50">
                  <th className="text-left px-4 py-3 text-sm font-medium text-zinc-400">
                    Address
                  </th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-zinc-400">
                    Panels
                  </th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-zinc-400">
                    Status
                  </th>
                  <th className="text-right px-4 py-3 text-sm font-medium text-zinc-400">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody>
                {samples.map((sample) => (
                  <tr
                    key={sample.id}
                    className="border-b border-zinc-800/50 hover:bg-zinc-900/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm text-white">
                      {sample.address}
                    </td>
                    <td className="px-4 py-3 text-sm text-zinc-300">
                      {sample.panel_count}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={sample.latest_run_status} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {sample.pdf_path && (
                          <a
                            href={`${API_BASE}/storage/v1/object/public/${sample.pdf_path}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-zinc-400 hover:text-white transition-colors"
                            title="View PDF"
                          >
                            <FileText className="w-4 h-4" />
                          </a>
                        )}
                        <Link
                          href={`/labeling/${sample.id}`}
                          className="text-zinc-400 hover:text-white transition-colors"
                          title="Open labeler"
                        >
                          <ArrowRight className="w-4 h-4" />
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
