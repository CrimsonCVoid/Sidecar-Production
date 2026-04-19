"use client";

import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ArrowRight, Tag, Loader2, MapPin } from "lucide-react";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface Sample {
  id: string;
  address: string;
  panel_count: number;
  latest_run_status: string | null;
  label_status: string;
  has_labels: boolean;
  dsm_storage_path: string | null;
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

function StatusBadge({ status }: { status: string | null }) {
  if (!status) {
    return <Badge variant="outline" className="text-zinc-500">New</Badge>;
  }
  const map: Record<string, { className: string; label: string }> = {
    pending: { className: "bg-zinc-700 text-zinc-200", label: "Pending" },
    building: { className: "bg-yellow-900 text-yellow-300", label: "Building" },
    complete: { className: "bg-green-900 text-green-300", label: "Complete" },
    failed: { className: "bg-red-900 text-red-300", label: "Failed" },
    flagged: { className: "bg-orange-900 text-orange-300", label: "Flagged" },
    accepted: { className: "bg-emerald-900 text-emerald-300", label: "Accepted" },
  };
  const s = map[status] ?? { className: "bg-zinc-700 text-zinc-200", label: status };
  return <Badge className={s.className}>{s.label}</Badge>;
}

function AddressInput({ onSuccess }: { onSuccess: () => void }) {
  const router = useRouter();
  const [address, setAddress] = useState("");
  const [isIngesting, setIsIngesting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!address.trim()) return;

    setIsIngesting(true);
    try {
      const res = await fetch(`${API_BASE}/api/solar/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address: address.trim() }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || err.message || "Ingest failed");
      }

      const data = await res.json();
      toast.success(`Downloaded solar data for ${data.formatted_address}`);
      setAddress("");
      onSuccess();
      router.push(`/labeling/${data.sample_id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to ingest address");
    } finally {
      setIsIngesting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2 mb-6">
      <div className="relative flex-1">
        <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder="Enter address to analyze (e.g. 123 Main St, Austin TX)"
          className="w-full pl-10 pr-4 py-2.5 bg-zinc-900 border border-zinc-800 rounded-lg text-sm text-white placeholder:text-zinc-500 focus:outline-none focus:border-zinc-600 transition-colors"
          disabled={isIngesting}
        />
      </div>
      <Button
        type="submit"
        disabled={isIngesting || !address.trim()}
        className="px-6"
      >
        {isIngesting ? (
          <>
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
            Downloading...
          </>
        ) : (
          "Analyze"
        )}
      </Button>
    </form>
  );
}

export default function DashboardPage() {
  const { data: samples, error, isLoading, mutate } = useSWR<Sample[]>(
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

        <AddressInput onSuccess={() => mutate()} />

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

        {samples && samples.length === 0 && !isLoading && (
          <div className="text-zinc-500 py-12 text-center">
            No samples yet. Enter an address above to get started.
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
                    Build Status
                  </th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-zinc-400">
                    Labels
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
                    <td className="px-4 py-3">
                      {sample.has_labels ? (
                        <span className="inline-flex items-center gap-1 text-xs text-emerald-400">
                          <Tag className="w-3 h-3" /> {sample.label_status}
                        </span>
                      ) : (
                        <span className="text-xs text-zinc-500">unlabeled</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
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
