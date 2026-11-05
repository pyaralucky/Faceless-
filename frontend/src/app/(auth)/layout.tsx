import { Video } from "lucide-react";
import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-4 py-12">
      <div
        aria-hidden
        className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[880px] -translate-x-1/2 rounded-full bg-accent-600/20 blur-3xl"
      />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-accent-600 shadow-lg shadow-accent-900/50">
            <Video className="h-5 w-5 text-white" />
          </div>
          <h1 className="text-xl font-semibold text-zinc-50">Faceless AI Studio</h1>
          <p className="mt-1 text-sm text-zinc-400">Research, script, render and publish faceless videos.</p>
        </div>
        {children}
      </div>
    </div>
  );
}
