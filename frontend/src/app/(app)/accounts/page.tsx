"use client";

import { Instagram, Link2, RefreshCw, ShieldCheck, Unplug, Youtube } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { PlatformIcon, platformLabel } from "@/components/platform";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardBody, CardHeader, ConfirmButton, EmptyState, ErrorState, LoadingBlock, Notice, PageHeader, Select, StatusBadge, Table } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtRelative } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import type { Platform, SocialAccount } from "@/lib/types";

function AccountsInner() {
  const { orgId, can } = useAuth();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const accounts = useQuery(`accounts:${orgId}`, () => api.social.accounts());
  const channels = useQuery(`channels:${orgId}`, () => api.channels.list());
  const channelName = useMemo(() => new Map((channels.data ?? []).map((c) => [c.id, c.name])), [channels.data]);
  const [connectChannel, setConnectChannel] = useState("");
  const [connecting, setConnecting] = useState<Platform | null>(null);
  const handled = useRef(false);

  // Handle OAuth return: ?connected=youtube&count=1 or ?error=...&platform=...
  useEffect(() => {
    if (handled.current) return;
    const connected = params.get("connected");
    const error = params.get("error");
    if (!connected && !error) return;
    handled.current = true;
    if (connected) {
      const count = Number(params.get("count") ?? "1");
      toast.success(`Connected ${count} ${platformLabel(connected)} account${count === 1 ? "" : "s"}`);
    } else if (error) {
      const platform = params.get("platform");
      toast.push("error", error === "access_denied" ? "Authorization was cancelled." : error, platform ? `${platformLabel(platform)} connection failed` : "Connection failed");
    }
    router.replace(pathname, { scroll: false });
  }, [params, router, pathname, toast]);

  const connect = async (platform: Platform) => {
    setConnecting(platform);
    try {
      const { authorization_url } = await api.social.authorize(platform, connectChannel || undefined);
      window.location.assign(authorization_url);
    } catch (e) {
      toast.error(e, `Could not start ${platformLabel(platform)} authorization`);
      setConnecting(null);
    }
  };

  const replace = (a: SocialAccount) => accounts.setData((prev) => (prev ?? []).map((x) => (x.id === a.id ? a : x)));

  return (
    <>
      <PageHeader title="Social accounts" description="Connect YouTube channels and Instagram professional accounts to publish directly." />

      {can("editor") && (
        <Card className="mb-6">
          <CardHeader title="Connect an account" description="You'll be redirected to the platform to grant access, then returned here." />
          <CardBody className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-[minmax(0,280px)_auto_auto] sm:items-end">
              <Select
                label="Assign to channel (optional)"
                value={connectChannel}
                onChange={(e) => setConnectChannel(e.target.value)}
                placeholder="No channel"
                options={(channels.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
              />
              <Button onClick={() => connect("youtube")} loading={connecting === "youtube"} disabled={Boolean(connecting)} icon={<Youtube className="h-4 w-4 text-rose-400" />}>
                Connect YouTube
              </Button>
              <Button onClick={() => connect("instagram")} loading={connecting === "instagram"} disabled={Boolean(connecting)} icon={<Instagram className="h-4 w-4 text-fuchsia-400" />}>
                Connect Instagram
              </Button>
            </div>
            <Notice tone="accent" icon={<ShieldCheck className="h-4 w-4" />}>
              Faceless AI Studio only uses the platforms&apos; <strong>official OAuth APIs</strong> (YouTube Data API v3 and the Instagram Graph API). We never ask for
              or store your passwords, and you can revoke access at any time here or from your Google / Meta account settings.
            </Notice>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="Connected accounts" />
        {accounts.loading && !accounts.data ? (
          <LoadingBlock />
        ) : accounts.error ? (
          <ErrorState error={accounts.error} onRetry={() => accounts.reload()} />
        ) : !accounts.data?.length ? (
          <EmptyState icon={<Link2 className="h-6 w-6" />} title="No accounts connected" description="Connect YouTube or Instagram to start publishing." />
        ) : (
          <Table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Status</th>
                <th>Channel</th>
                <th>Token expires</th>
                <th>Scopes</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {accounts.data.map((a) => (
                <tr key={a.id}>
                  <td>
                    <div className="flex items-center gap-3">
                      {a.avatar_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={a.avatar_url} alt="" className="h-8 w-8 rounded-full bg-zinc-800 object-cover" referrerPolicy="no-referrer" />
                      ) : (
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-zinc-800">
                          <PlatformIcon platform={a.platform} />
                        </div>
                      )}
                      <div className="min-w-0">
                        <p className="truncate font-medium text-zinc-100">{a.display_name}</p>
                        <p className="flex items-center gap-1 text-xs text-zinc-500">
                          <PlatformIcon platform={a.platform} className="h-3 w-3" /> {platformLabel(a.platform)} · {a.external_id}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td>
                    <StatusBadge status={a.status} />
                  </td>
                  <td className="min-w-[180px]">
                    {can("editor") ? (
                      <Select
                        aria-label={`Channel for ${a.display_name}`}
                        className="h-8"
                        value={a.channel_id ?? ""}
                        placeholder="Unassigned"
                        options={(channels.data ?? []).map((c) => ({ value: c.id, label: c.name }))}
                        onChange={async (e) => {
                          try {
                            replace(await api.social.assign(a.id, e.target.value || null));
                            toast.success("Channel assignment updated");
                          } catch (err) {
                            toast.error(err);
                          }
                        }}
                      />
                    ) : (
                      (a.channel_id && channelName.get(a.channel_id)) || <span className="text-zinc-500">Unassigned</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap text-xs">
                    {a.token_expires_at ? (
                      <span title={fmtDate(a.token_expires_at)} className={new Date(a.token_expires_at) < new Date() ? "text-amber-300" : "text-zinc-400"}>
                        {fmtRelative(a.token_expires_at)}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="max-w-[200px]">
                    <div className="flex flex-wrap gap-1">
                      {a.scopes.slice(0, 3).map((s) => (
                        <Badge key={s} className="max-w-[180px] truncate" tone="zinc">
                          {s.replace(/^https:\/\/www\.googleapis\.com\/auth\//, "")}
                        </Badge>
                      ))}
                      {a.scopes.length > 3 && <Badge>+{a.scopes.length - 3}</Badge>}
                    </div>
                  </td>
                  <td>
                    <div className="flex justify-end gap-1">
                      {can("editor") && (
                        <Button
                          size="xs"
                          variant="ghost"
                          icon={<RefreshCw className="h-3.5 w-3.5" />}
                          onClick={async () => {
                            try {
                              replace(await api.social.refresh(a.id));
                              toast.success("Token refreshed");
                            } catch (err) {
                              toast.error(err, "Token refresh failed");
                            }
                          }}
                        >
                          Refresh
                        </Button>
                      )}
                      {can("admin") && (
                        <ConfirmButton
                          size="xs"
                          icon={<Unplug className="h-3.5 w-3.5" />}
                          title="Disconnect account"
                          confirmLabel="Disconnect"
                          message={
                            <>
                              Disconnect <strong>{a.display_name}</strong>? Access tokens are revoked and scheduled posts to this account will fail.
                            </>
                          }
                          onConfirm={async () => {
                            try {
                              await api.social.disconnect(a.id);
                              accounts.setData((prev) => (prev ?? []).filter((x) => x.id !== a.id));
                              toast.success("Account disconnected");
                            } catch (err) {
                              toast.error(err);
                            }
                          }}
                        >
                          Disconnect
                        </ConfirmButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

export default function AccountsPage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <AccountsInner />
    </Suspense>
  );
}
