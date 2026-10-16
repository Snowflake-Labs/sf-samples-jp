import { readFileSync } from "node:fs";

/**
 * Reads a secret declared under `secrets:` in app.yml.
 *
 * Snowflake App Runtime mounts each secret as files under `/secrets/<mount>/`
 * and does NOT expose it as an environment variable. A GENERIC_STRING secret
 * produces a single file, `secret_string`. Reading `process.env.<mount>`
 * instead silently yields `undefined`, which surfaced as node-postgres failing
 * with "SASL: SCRAM-SERVER-FIRST-MESSAGE: client password must be a string".
 *
 * The file is read fresh on every call so that a secret rotation takes effect
 * without a redeploy - Snowflake updates the file content in place.
 *
 * Falls back to the environment variable of the same name, which is how local
 * development supplies these values via `.env`.
 */
export function readSecret(mount: string): string | undefined {
  try {
    const value = readFileSync(`/secrets/${mount}/secret_string`, "utf8").trim();
    if (value) return value;
  } catch {
    // Not running on App Runtime, or the secret is not mounted. Fall through to
    // the environment so local development keeps working.
  }
  return process.env[mount] || undefined;
}
