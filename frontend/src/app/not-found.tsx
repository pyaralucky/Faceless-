import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <p className="text-sm font-medium text-accent-400">404</p>
      <h1 className="text-2xl font-semibold text-zinc-50">Page not found</h1>
      <p className="text-sm text-zinc-400">The page you are looking for does not exist or has moved.</p>
      <Link href="/dashboard" className="rounded-md bg-accent-600 px-4 py-2 text-sm font-medium text-white hover:bg-accent-500">
        Back to dashboard
      </Link>
    </main>
  );
}
