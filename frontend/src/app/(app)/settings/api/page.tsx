"use client";

import { ArrowDown, ArrowUp, FlaskConical, KeyRound, Pencil, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  Checkbox,
  ConfirmButton,
  EmptyState,
  ErrorState,
  FormError,
  Input,
  JsonEditor,
  LoadingBlock,
  Modal,
  NoAccess,
  Notice,
  PageHeader,
  Select,
  Table,
} from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtRelative, humanize } from "@/lib/format";
import { useQuery } from "@/lib/hooks";
import { LLM_PROVIDERS, type ApiCatalog, type Credential, type CredentialTestResult, type LLMProvider, type ModelRoute, type ModelTarget } from "@/lib/types";

const PROVIDER_LABEL: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google Gemini",
  openrouter: "OpenRouter",
  azure_openai: "Azure OpenAI",
  ollama: "Ollama",
  mock: "Mock (testing)",
};
const providerLabel = (p: string) => PROVIDER_LABEL[p] ?? p;

// ------------------------------------------------------------------ credentials

function CredentialModal({ credential, providers, onClose, onSaved }: { credential?: Credential; providers: string[]; onClose: () => void; onSaved: (c: Credential) => void }) {
  const toast = useToast();
  const [provider, setProvider] = useState<LLMProvider>((credential?.provider ?? providers[0] ?? "openai") as LLMProvider);
  const [label, setLabel] = useState(credential?.label ?? "default");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(credential?.base_url ?? "");
  const [config, setConfig] = useState<Record<string, unknown>>(credential?.config ?? {});
  const [isActive, setIsActive] = useState(credential?.is_active ?? true);
  const [valid, setValid] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fe, setFe] = useState<Record<string, string>>({});

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setFe({});
    try {
      const saved = credential
        ? await api.apiConfig.updateCredential(credential.id, {
            ...(apiKey ? { api_key: apiKey } : {}),
            base_url: baseUrl.trim() || null,
            is_active: isActive,
            config,
          })
        : await api.apiConfig.createCredential({ provider, label: label.trim() || "default", api_key: apiKey, base_url: baseUrl.trim() || null, config });
      toast.success(credential ? "Credential updated" : "Credential added");
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFe(err.fieldErrors);
    } finally {
      setBusy(false);
    }
  };

  const needsUrl = provider === "azure_openai" || provider === "ollama";

  return (
    <Modal
      open
      onClose={onClose}
      title={credential ? `Edit ${providerLabel(credential.provider)} · ${credential.label}` : "Add provider credential"}
      description="API keys are encrypted at rest and never shown again after saving."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="cred-form" loading={busy} disabled={!valid || (!credential && !apiKey)}>
            Save
          </Button>
        </>
      }
    >
      <form id="cred-form" onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="Provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value as LLMProvider)}
            options={providers.map((p) => ({ value: p, label: providerLabel(p) }))}
            disabled={Boolean(credential)}
            error={fe.provider}
          />
          <Input label="Label" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} disabled={Boolean(credential)} error={fe.label} />
        </div>
        <Input
          label={credential ? "New API key" : "API key"}
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required={!credential}
          placeholder={credential ? `Current: ${credential.key_hint} — leave blank to keep` : "sk-…"}
          error={fe.api_key}
        />
        <Input
          label="Base URL"
          type="url"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder={provider === "ollama" ? "http://ollama:11434" : provider === "azure_openai" ? "https://<resource>.openai.azure.com" : "Optional override"}
          hint={needsUrl ? "Required for this provider." : undefined}
          error={fe.base_url}
        />
        <JsonEditor
          label="Provider config (JSON)"
          value={config}
          onChange={setConfig}
          onValidity={setValid}
          rows={4}
          hint='e.g. {"api_version": "2024-06-01", "default_model": "…"}'
        />
        {credential && <Checkbox label="Active" checked={isActive} onChange={setIsActive} />}
        <FormError error={error} />
      </form>
    </Modal>
  );
}

function TestButton({ cred, suggestions }: { cred: Credential; suggestions: string[] }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState(suggestions[0] ?? "");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CredentialTestResult | null>(null);
  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const r = await api.apiConfig.testCredential(cred.id, model || undefined);
      setResult(r);
      if (r.ok) toast.success(`Connection OK (${r.model})`);
      else toast.push("error", r.error ?? "Test failed", "Connection test failed");
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
    }
  };
  const listId = `test-models-${cred.id}`;
  return (
    <>
      <Button size="xs" variant="ghost" icon={<FlaskConical className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>
        Test
      </Button>
      {open && (
        <Modal
          open
          onClose={() => setOpen(false)}
          size="sm"
          title={`Test ${providerLabel(cred.provider)} · ${cred.label}`}
          description="Sends a tiny prompt to verify the key works."
          footer={
            <Button variant="primary" loading={busy} onClick={run}>
              Run test
            </Button>
          }
        >
          <Input label="Model" list={listId} value={model} onChange={(e) => setModel(e.target.value)} placeholder="Provider default" />
          <datalist id={listId}>
            {suggestions.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
          {result && (
            <div className="mt-4">
              {result.ok ? (
                <Notice tone="green">
                  <p className="font-medium">Success · {result.model}</p>
                  <p className="text-xs">
                    Reply: “{result.reply}” · {result.prompt_tokens}+{result.completion_tokens} tokens
                  </p>
                </Notice>
              ) : (
                <Notice tone="red">{result.error}</Notice>
              )}
            </div>
          )}
        </Modal>
      )}
    </>
  );
}

function Credentials({ catalog }: { catalog: ApiCatalog }) {
  const { orgId } = useAuth();
  const toast = useToast();
  const creds = useQuery(`creds:${orgId}`, () => api.apiConfig.credentials());
  const [editing, setEditing] = useState<Credential | null>(null);
  const [creating, setCreating] = useState(false);
  const upsert = (c: Credential) =>
    creds.setData((prev) => (prev?.some((x) => x.id === c.id) ? prev.map((x) => (x.id === c.id ? c : x)) : [...(prev ?? []), c]));

  return (
    <Card>
      <CardHeader
        title="Provider credentials"
        description="Bring your own keys. Agents use the routes below to pick a provider and model."
        actions={
          <Button size="sm" variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
            Add credential
          </Button>
        }
      />
      {creds.loading && !creds.data ? (
        <LoadingBlock />
      ) : creds.error ? (
        <ErrorState error={creds.error} onRetry={() => creds.reload()} />
      ) : !creds.data?.length ? (
        <EmptyState icon={<KeyRound className="h-6 w-6" />} title="No credentials yet" description="Add an API key for OpenAI, Anthropic, Google or another provider." />
      ) : (
        <Table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Label</th>
              <th>Key</th>
              <th>Base URL</th>
              <th>Status</th>
              <th>Updated</th>
              <th className="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {creds.data.map((c) => (
              <tr key={c.id}>
                <td className="font-medium text-zinc-200">{providerLabel(c.provider)}</td>
                <td>{c.label}</td>
                <td className="font-mono text-xs text-zinc-400">{c.key_hint}</td>
                <td className="max-w-[200px] truncate text-xs text-zinc-500">{c.base_url ?? "—"}</td>
                <td>
                  <button
                    onClick={async () => {
                      try {
                        upsert(await api.apiConfig.updateCredential(c.id, { is_active: !c.is_active }));
                      } catch (e) {
                        toast.error(e);
                      }
                    }}
                    title="Toggle active"
                  >
                    <Badge tone={c.is_active ? "green" : "zinc"}>{c.is_active ? "Active" : "Disabled"}</Badge>
                  </button>
                </td>
                <td className="whitespace-nowrap text-zinc-500">{fmtRelative(c.updated_at)}</td>
                <td>
                  <div className="flex justify-end gap-1">
                    <TestButton cred={c} suggestions={catalog.suggested_models[c.provider] ?? []} />
                    <Button size="xs" variant="ghost" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(c)}>
                      Edit
                    </Button>
                    <ConfirmButton
                      size="xs"
                      icon={<Trash2 className="h-3.5 w-3.5" />}
                      aria-label="Delete credential"
                      title="Delete credential"
                      confirmLabel="Delete"
                      message={`Delete the ${providerLabel(c.provider)} key “${c.label}”? Agents routed to this provider will fail or fall back.`}
                      onConfirm={async () => {
                        try {
                          await api.apiConfig.deleteCredential(c.id);
                          creds.setData((prev) => (prev ?? []).filter((x) => x.id !== c.id));
                          toast.success("Credential deleted");
                        } catch (e) {
                          toast.error(e);
                        }
                      }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {creating && <CredentialModal providers={catalog.providers} onClose={() => setCreating(false)} onSaved={upsert} />}
      {editing && <CredentialModal credential={editing} providers={catalog.providers} onClose={() => setEditing(null)} onSaved={upsert} />}
    </Card>
  );
}

// ------------------------------------------------------------------ model routes

function ModelInput({ label, provider, value, onChange, catalog, id }: { label?: string; provider: string; value: string; onChange: (v: string) => void; catalog: ApiCatalog; id: string }) {
  const listId = `${id}-models`;
  return (
    <>
      <Input label={label} aria-label={label ? undefined : "Model"} list={listId} value={value} onChange={(e) => onChange(e.target.value)} maxLength={120} placeholder="model id" required />
      <datalist id={listId}>
        {(catalog.suggested_models[provider] ?? []).map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>
    </>
  );
}

function RouteEditor({ agent, route, catalog, editable, onSaved, onDeleted }: { agent: string; route?: ModelRoute; catalog: ApiCatalog; editable: boolean; onSaved: (r: ModelRoute) => void; onDeleted: () => void }) {
  const toast = useToast();
  const firstProvider = (catalog.providers[0] ?? "openai") as LLMProvider;
  const [provider, setProvider] = useState<LLMProvider>(route?.provider ?? firstProvider);
  const [model, setModel] = useState(route?.model ?? catalog.suggested_models[route?.provider ?? firstProvider]?.[0] ?? "");
  const [temperature, setTemperature] = useState(route?.temperature ?? 0.7);
  const [maxTokens, setMaxTokens] = useState(route?.max_tokens ?? 4096);
  const [fallbacks, setFallbacks] = useState<ModelTarget[]>(route?.fallbacks ?? []);
  const [busy, setBusy] = useState(false);
  const [fe, setFe] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState(Boolean(route) || agent === "*");

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFe({});
    try {
      const r = await api.apiConfig.upsertRoute(agent, { provider, model: model.trim(), temperature, max_tokens: maxTokens, fallbacks: fallbacks.filter((f) => f.model.trim()) });
      onSaved(r);
      toast.success(`Route for ${agent === "*" ? "default" : humanize(agent)} saved`);
    } catch (err) {
      if (err instanceof ApiError) setFe(err.fieldErrors);
      toast.error(err);
    } finally {
      setBusy(false);
    }
  };

  const moveFb = (i: number, d: -1 | 1) =>
    setFallbacks((f) => {
      const j = i + d;
      if (j < 0 || j >= f.length) return f;
      const n = [...f];
      [n[i], n[j]] = [n[j], n[i]];
      return n;
    });

  const title = agent === "*" ? "Default (all agents)" : humanize(agent);

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/30">
      <button type="button" className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left" onClick={() => setExpanded((x) => !x)} aria-expanded={expanded}>
        <div className="flex items-center gap-2">
          <span className="font-medium text-zinc-100">{title}</span>
          {route ? (
            <Badge tone="accent">
              {providerLabel(route.provider)} · {route.model}
            </Badge>
          ) : (
            <Badge>{agent === "*" ? "Not configured" : "Inherits default"}</Badge>
          )}
          {route && route.fallbacks.length > 0 && <Badge tone="zinc">+{route.fallbacks.length} fallback</Badge>}
        </div>
        <span className="text-xs text-zinc-500">{expanded ? "Hide" : "Configure"}</span>
      </button>
      {expanded && (
        <form onSubmit={save} className="space-y-4 border-t border-zinc-800 p-4">
          <fieldset disabled={!editable} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Select
                label="Provider"
                value={provider}
                onChange={(e) => {
                  const p = e.target.value as LLMProvider;
                  setProvider(p);
                  if (!model || !(catalog.suggested_models[provider] ?? []).length || (catalog.suggested_models[provider] ?? []).includes(model)) setModel(catalog.suggested_models[p]?.[0] ?? "");
                }}
                options={catalog.providers.map((p) => ({ value: p, label: providerLabel(p) }))}
                error={fe.provider}
              />
              <div>
                <ModelInput id={`route-${agent}`} label="Model" provider={provider} value={model} onChange={setModel} catalog={catalog} />
              </div>
              <Input label="Temperature" type="number" step={0.05} min={0} max={2} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} error={fe.temperature} />
              <Input label="Max tokens" type="number" min={64} max={200000} step={64} value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} error={fe.max_tokens} />
            </div>
            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Fallbacks (tried in order)</p>
                <Button size="xs" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setFallbacks((f) => [...f, { provider: firstProvider, model: catalog.suggested_models[firstProvider]?.[0] ?? "" }])}>
                  Add fallback
                </Button>
              </div>
              {fallbacks.length === 0 ? (
                <p className="text-xs text-zinc-500">No fallbacks. If the primary model fails, the agent step fails.</p>
              ) : (
                <ol className="space-y-2">
                  {fallbacks.map((f, i) => (
                    <li key={i} className="grid grid-cols-[24px_1fr_1fr_auto] items-center gap-2">
                      <span className="text-xs tabular-nums text-zinc-500">{i + 1}.</span>
                      <Select
                        aria-label={`Fallback ${i + 1} provider`}
                        value={f.provider}
                        onChange={(e) => setFallbacks((fs) => fs.map((x, j) => (j === i ? { provider: e.target.value as LLMProvider, model: catalog.suggested_models[e.target.value]?.[0] ?? "" } : x)))}
                        options={catalog.providers.map((p) => ({ value: p, label: providerLabel(p) }))}
                      />
                      <div>
                        <ModelInput id={`fb-${agent}-${i}`} provider={f.provider} value={f.model} onChange={(v) => setFallbacks((fs) => fs.map((x, j) => (j === i ? { ...x, model: v } : x)))} catalog={catalog} />
                      </div>
                      <div className="flex">
                        <Button size="xs" variant="ghost" icon={<ArrowUp className="h-3.5 w-3.5" />} onClick={() => moveFb(i, -1)} disabled={i === 0} aria-label="Move up" />
                        <Button size="xs" variant="ghost" icon={<ArrowDown className="h-3.5 w-3.5" />} onClick={() => moveFb(i, 1)} disabled={i === fallbacks.length - 1} aria-label="Move down" />
                        <Button size="xs" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setFallbacks((fs) => fs.filter((_, j) => j !== i))} aria-label="Remove fallback" />
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </fieldset>
          {editable && (
            <div className="flex justify-end gap-2">
              {route && (
                <ConfirmButton
                  size="sm"
                  icon={<RotateCcw className="h-4 w-4" />}
                  title="Reset route"
                  confirmLabel="Reset"
                  message={agent === "*" ? "Remove the default route? Agents without their own route will use the server default." : `Remove the ${title} route? It will inherit the default route.`}
                  onConfirm={async () => {
                    try {
                      await api.apiConfig.deleteRoute(agent);
                      toast.success("Route removed");
                      onDeleted();
                    } catch (e) {
                      toast.error(e);
                    }
                  }}
                >
                  Reset
                </ConfirmButton>
              )}
              <Button type="submit" size="sm" variant="primary" loading={busy} disabled={!model.trim()} icon={<Save className="h-4 w-4" />}>
                Save route
              </Button>
            </div>
          )}
        </form>
      )}
    </div>
  );
}

function Routes({ catalog }: { catalog: ApiCatalog }) {
  const { orgId, can } = useAuth();
  const routes = useQuery(`routes:${orgId}`, () => api.apiConfig.routes());
  const agents = ["*", ...catalog.agents];
  const byAgent = new Map((routes.data ?? []).map((r) => [r.agent_name, r]));
  return (
    <Card>
      <CardHeader title="Model routing" description="Choose the provider & model per agent. '*' is the default for agents without their own route." />
      <CardBody>
        {routes.loading && !routes.data ? (
          <LoadingBlock />
        ) : routes.error ? (
          <ErrorState error={routes.error} onRetry={() => routes.reload()} />
        ) : (
          <div className="space-y-3">
            {agents.map((a) => (
              <RouteEditor
                key={`${a}:${byAgent.get(a)?.updated_at ?? "none"}`}
                agent={a}
                route={byAgent.get(a)}
                catalog={catalog}
                editable={can("admin")}
                onSaved={(r) => routes.setData((prev) => [...(prev ?? []).filter((x) => x.agent_name !== r.agent_name), r])}
                onDeleted={() => routes.setData((prev) => (prev ?? []).filter((x) => x.agent_name !== a))}
              />
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

export default function ApiSettingsPage() {
  const { orgId, can } = useAuth();
  const catalog = useQuery(`catalog:${orgId}`, () => api.apiConfig.catalog());
  const fallbackCatalog: ApiCatalog = { providers: [...LLM_PROVIDERS], agents: [], suggested_models: {} };

  return (
    <>
      <PageHeader title="API & models" description="Provider credentials and per-agent model routing for this organization." />
      {!can("admin") ? (
        <NoAccess need="admin" />
      ) : catalog.loading && !catalog.data ? (
        <LoadingBlock />
      ) : catalog.error ? (
        <Card>
          <ErrorState error={catalog.error} onRetry={() => catalog.reload()} />
        </Card>
      ) : (
        <div className="space-y-6">
          <Credentials catalog={catalog.data ?? fallbackCatalog} />
          <Routes catalog={catalog.data ?? fallbackCatalog} />
        </div>
      )}
    </>
  );
}
