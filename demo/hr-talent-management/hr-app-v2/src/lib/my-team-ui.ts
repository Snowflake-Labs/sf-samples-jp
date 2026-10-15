// Labels and colours for the line manager's progress states (shared by list and input screens).
export type Progress = "not_started" | "draft" | "ai_scored" | "returned" | "submitted" | "completed";

export const PROGRESS_META: Record<Progress, { label: string; cls: string; next: string }> = {
  returned: { label: "差し戻し", cls: "border-red-500/50 bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300", next: "直して再提出" },
  not_started: { label: "未着手", cls: "border-muted-foreground/30 text-muted-foreground", next: "コメントを書く" },
  draft: { label: "下書き", cls: "border-sky-500/50 text-sky-700 dark:text-sky-300", next: "AIで採点" },
  ai_scored: { label: "AI採点済み", cls: "border-violet-500/50 text-violet-700 dark:text-violet-300", next: "スコア確認・提出" },
  submitted: { label: "提出済み", cls: "border-emerald-500/50 text-emerald-700 dark:text-emerald-300", next: "人事確認待ち" },
  completed: { label: "確定", cls: "border-emerald-600 bg-emerald-50 text-emerald-800 dark:bg-emerald-950", next: "確定済み" },
};
