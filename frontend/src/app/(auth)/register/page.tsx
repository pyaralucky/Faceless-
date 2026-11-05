"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { Button, Card, FormError, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { passwordProblem } from "@/lib/format";

export default function RegisterPage() {
  const { register, status } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "", full_name: "", organization_name: "" });
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (status === "authenticated") router.replace("/dashboard");
  }, [status, router]);

  const pwProblem = passwordProblem(form.password);
  const set = (k: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (pwProblem) return;
    setBusy(true);
    setError(null);
    setFieldErrors({});
    try {
      await register({
        email: form.email.trim(),
        password: form.password,
        full_name: form.full_name.trim(),
        organization_name: form.organization_name.trim(),
      });
      router.replace("/dashboard");
    } catch (err) {
      setError(err);
      if (err instanceof ApiError) setFieldErrors(err.fieldErrors);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-6 sm:p-8">
      <h2 className="mb-1 text-lg font-semibold text-zinc-50">Create your account</h2>
      <p className="mb-6 text-sm text-zinc-400">You&apos;ll be the owner of a new organization.</p>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Input label="Full name" autoComplete="name" value={form.full_name} onChange={set("full_name")} maxLength={200} error={fieldErrors.full_name} />
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          value={form.email}
          onChange={set("email")}
          required
          error={fieldErrors.email}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          value={form.password}
          onChange={set("password")}
          onBlur={() => setTouched(true)}
          required
          minLength={10}
          maxLength={256}
          error={fieldErrors.password ?? (touched && form.password ? pwProblem : null)}
          hint="At least 10 characters, mixing letters with digits or symbols."
        />
        <Input
          label="Organization name"
          value={form.organization_name}
          onChange={set("organization_name")}
          placeholder="My Studio"
          maxLength={200}
          error={fieldErrors.organization_name}
          hint="Defaults to your name if left blank."
        />
        <FormError error={error} />
        <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!form.email || !form.password}>
          Create account
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-zinc-400">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-accent-300 hover:text-accent-200">
          Sign in
        </Link>
      </p>
    </Card>
  );
}
