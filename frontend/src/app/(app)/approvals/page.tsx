"use client";

import { Check, ClipboardCheck, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, EmptyState, ErrorState, LoadingBlock, Modal, PageHeader, Pagination, StatusBadge, Table, Tabs, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtRelative } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import type { Approval, Page } from "@/lib/types";

const LIMIT = 50;
type View = "pending" | "history";

function DecisionModal({ approval, decision, title, onClose, onDone }: { approval: Approval; decision: "approve" | "reject"; title: string; onClose: () => void; onDone: (a: Approval) => void }) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const a = await api.approvals.decide(approval.id, { decision, note });
      toast.success(decision === "approve" ? "Approved" : "Rejected");
      onDone(a);
      onClose();
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      onClose={onClose}
      size="sm"
      title={decision === "approve" ? "Approve" : "Reject"}
      description={title}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={decision === "approve" ? "success" : "danger"} loading={busy} onClick={submit}>
            {decision === "approve" ? "Approve" : "Reject"}
          </Button>
        </>
      }
    >
      {approval.request_note && (
        <p className="mb-3 rounded-md bg-zinc-800/60 p-3 text-sm text-zinc-300">
          <span className="block text-xs uppercase tracking-wide text-zinc-500">Request note</span>
          {approval.request_note}
        </p>
      )}
      <Textarea
        label={decision === "reject" ? "Reason (shared with the requester)" : "Note (optional)"}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        maxLength={2000}
        rows={4}
      />
    </Modal>
  );
}

export default function ApprovalsPage() {
  const { orgId, can } = useAuth();
  const [view, setView] = useState<View>("pending");
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [view]);

  const list = useQuery<Page<Approval>>(
    `approvals:${orgId}:${view}:${offset}`,
    () => api.approvals.list({ decided: view === "history", limit: LIMIT, offset }),
    { interval: view === "pending" ? 15_000 : false },
  );

  const [deciding, setDeciding] = useState<{ a: Approval; d: "approve" | "reject" } | null>(null);
  const reviewer = can("reviewer");

  return (
    <>
      <PageHeader title="Approvals" description="Review videos before they are published to connected accounts." />
      <Tabs
        className="mb-6"
        value={view}
        onChange={setView}
        tabs={[
          { value: "pending", label: "Pending", count: view === "pending" ? list.data?.total : undefined },
          { value: "history", label: "History" },
        ]}
      />
      <Card>
        {list.loading && !list.data ? (
          <LoadingBlock />
        ) : list.error ? (
          <ErrorState error={list.error} onRetry={() => list.reload()} />
        ) : !list.data?.items.length ? (
          <EmptyState
            icon={<ClipboardCheck className="h-6 w-6" />}
            title={view === "pending" ? "Nothing waiting for review" : "No decisions yet"}
            description={view === "pending" ? "Approval requests created when scheduling posts on channels that require approval appear here." : undefined}
          />
        ) : (
          <>
            <Table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Requested</th>
                  <th>Note</th>
                  <th>Status</th>
                  {view === "history" && <th>Decision note</th>}
                  {view === "history" && <th>Decided</th>}
                  {view === "pending" && reviewer && <th className="text-right">Decision</th>}
                </tr>
              </thead>
              <tbody>
                {list.data.items.map((a) => (
                  <tr key={a.id}>
                    <td className="max-w-xs">
                      <Link href={`/projects/${a.project_id}?tab=${a.publish_job_id ? "publish" : "overview"}`} className="font-medium text-zinc-100 hover:text-accent-300">
                        {a.project_title ?? "Deleted project"}
                      </Link>
                      <p className="text-xs text-zinc-500">{a.publish_job_id ? "Publish job" : "Project review"}</p>
                    </td>
                    <td className="whitespace-nowrap text-zinc-400" title={fmtDate(a.created_at)}>
                      {fmtRelative(a.created_at)}
                    </td>
                    <td className="max-w-xs text-zinc-400">{a.request_note || "—"}</td>
                    <td>
                      <StatusBadge status={a.status} />
                    </td>
                    {view === "history" && <td className="max-w-xs text-zinc-400">{a.decision_note || "—"}</td>}
                    {view === "history" && <td className="whitespace-nowrap text-zinc-500">{fmtDate(a.decided_at)}</td>}
                    {view === "pending" && reviewer && (
                      <td>
                        <div className="flex justify-end gap-2">
                          <Button size="sm" variant="success" icon={<Check className="h-4 w-4" />} onClick={() => setDeciding({ a, d: "approve" })}>
                            Approve
                          </Button>
                          <Button size="sm" variant="danger" icon={<X className="h-4 w-4" />} onClick={() => setDeciding({ a, d: "reject" })}>
                            Reject
                          </Button>
                        </div>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination total={list.data.total} limit={LIMIT} offset={offset} onChange={setOffset} />
          </>
        )}
      </Card>
      {deciding && (
        <DecisionModal
          approval={deciding.a}
          decision={deciding.d}
          title={deciding.a.project_title ?? ""}
          onClose={() => setDeciding(null)}
          onDone={(a) => list.setData((prev) => (prev ? { ...prev, items: prev.items.filter((x) => x.id !== a.id), total: Math.max(0, prev.total - 1) } : prev))}
        />
      )}
    </>
  );
}
