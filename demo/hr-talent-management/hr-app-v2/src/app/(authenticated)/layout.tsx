"use client";

import { useAuth } from "@/lib/auth-context";
import { HonbuProvider } from "@/lib/honbu-context";
import { DataPathProvider } from "@/lib/data-path-context";
import { useRouter, usePathname } from "next/navigation";
import { useEffect } from "react";
import AppShell from "@/components/app-shell";
import { FeedbackButton } from "@/components/feedback-button";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!loading && !user) {
      router.push("/login");
    }
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-pulse text-muted-foreground">読み込み中...</div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <DataPathProvider>
      <AppShell>
        <HonbuProvider>{children}</HonbuProvider>
        <FeedbackButton page={pathname} />
      </AppShell>
    </DataPathProvider>
  );
}
