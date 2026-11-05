"use client";

import { KeyRound, Save } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardBody, CardHeader, FormError, Input, KeyValue, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, humanize, passwordProblem } from "@/lib/format";

export default function ProfilePage() {
  const { user, reloadUser, memberships } = useAuth();
  const toast = useToast();
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [savingName, setSavingName] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [savingPw, setSavingPw] = useState(false);
  const [pwError, setPwError] = useState<unknown>(null);
  const [pwFe, setPwFe] = useState<Record<string, string>>({});

  const saveName = async (e: FormEvent) => {
    e.preventDefault();
    setSavingName(true);
    try {
      await api.users.updateMe({ full_name: fullName.trim() });
      await reloadUser();
      toast.success("Profile updated");
    } catch (err) {
      toast.error(err);
    } finally {
      setSavingName(false);
    }
  };

  const problem = next ? passwordProblem(next) : null;
  const mismatch = confirm && confirm !== next ? "Passwords do not match" : null;

  const changePw = async (e: FormEvent) => {
    e.preventDefault();
    if (problem || mismatch) return;
    setSavingPw(true);
    setPwError(null);
    setPwFe({});
    try {
      await api.auth.changePassword({ current_password: current, new_password: next });
      toast.success("Password changed");
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setPwError(err);
      if (err instanceof ApiError) setPwFe(err.fieldErrors);
    } finally {
      setSavingPw(false);
    }
  };

  if (!user) return null;

  return (
    <>
      <PageHeader title="Profile" description="Your personal account settings." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Account" />
          <CardBody className="space-y-6">
            <KeyValue
              items={[
                ["Email", user.email],
                ["Email verified", user.email_verified ? "Yes" : "No"],
                ["Last sign-in", fmtDate(user.last_login_at)],
                ["Member since", fmtDate(user.created_at)],
              ]}
            />
            <form onSubmit={saveName} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Input label="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={200} wrapperClassName="flex-1" />
              <Button type="submit" variant="primary" loading={savingName} icon={<Save className="h-4 w-4" />}>
                Save
              </Button>
            </form>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Change password" />
          <CardBody>
            <form onSubmit={changePw} className="space-y-4">
              <Input label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required error={pwFe.current_password} />
              <Input
                label="New password"
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
                maxLength={256}
                error={pwFe.new_password ?? problem}
                hint="At least 10 characters, mixing letters with digits or symbols."
              />
              <Input label="Confirm new password" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required error={mismatch} />
              <FormError error={pwError} />
              <div className="flex justify-end">
                <Button type="submit" variant="primary" loading={savingPw} disabled={!current || !next || Boolean(problem) || confirm !== next} icon={<KeyRound className="h-4 w-4" />}>
                  Update password
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Organizations" />
          <CardBody>
            {memberships.length === 0 ? (
              <p className="text-sm text-zinc-500">You are not a member of any organization.</p>
            ) : (
              <ul className="divide-y divide-zinc-800">
                {memberships.map((m) => (
                  <li key={m.organization_id} className="flex items-center justify-between py-2 text-sm">
                    <span className="text-zinc-200">
                      {m.organization_name} <span className="text-xs text-zinc-500">/{m.organization_slug}</span>
                    </span>
                    <Badge>{humanize(m.role)}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
