import { describe, expect, it } from "vitest";
import { isChunkError, shouldAutoReload } from "@/lib/chunk-error";

describe("isChunkError", () => {
  it("detects Next.js chunk load failures", () => {
    expect(isChunkError({ name: "ChunkLoadError", message: "Loading chunk 123 failed." })).toBe(true);
    expect(isChunkError({ name: "TypeError", message: "Failed to fetch dynamically imported module: /_next/x.js" })).toBe(true);
    expect(isChunkError({ name: "TypeError", message: "Importing a module script failed." })).toBe(true);
  });
  it("ignores ordinary errors", () => {
    expect(isChunkError({ name: "TypeError", message: "Cannot read properties of undefined (reading 'map')" })).toBe(false);
    expect(isChunkError({ name: "TypeError", message: "Failed to fetch" })).toBe(false);
    expect(isChunkError({})).toBe(false);
  });
});

describe("shouldAutoReload", () => {
  const chunk = { name: "ChunkLoadError", message: "Loading chunk 1 failed." };
  it("reloads a chunk error when not reloaded recently", () => {
    expect(shouldAutoReload(chunk, 0, 1_000_000)).toBe(true);
  });
  it("does not reload again within 30 seconds", () => {
    expect(shouldAutoReload(chunk, 1_000_000, 1_020_000)).toBe(false);
    expect(shouldAutoReload(chunk, 1_000_000, 1_030_001)).toBe(true);
  });
  it("never reloads ordinary errors", () => {
    expect(shouldAutoReload({ name: "TypeError", message: "x is undefined" }, 0, 1_000_000)).toBe(false);
  });
});
