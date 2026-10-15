// 再デプロイ後、古いタブが旧ビルドのチャンクを読みに行くと失敗する。
// そのときだけ自動で再読み込みし、30 秒以内の連続リロードはしない。

export const RELOAD_KEY = "hr-chunk-reload-at";
export const RELOAD_COOLDOWN_MS = 30_000;

export function isChunkError(error: { name?: string; message?: string }): boolean {
  return /ChunkLoadError|Loading chunk|Failed to fetch dynamically imported module|Importing a module script failed/i
    .test(`${error.name ?? ""} ${error.message ?? ""}`);
}

export function shouldAutoReload(error: { name?: string; message?: string }, lastReloadAt: number, now: number): boolean {
  return isChunkError(error) && now - lastReloadAt > RELOAD_COOLDOWN_MS;
}
