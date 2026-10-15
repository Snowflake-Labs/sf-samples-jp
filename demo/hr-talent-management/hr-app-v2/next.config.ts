import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactCompiler: true,
  // `output: "standalone"` removed as cleanup, not as a fix. The Snowflake App
  // Runtime builder launches the app with `npm start` (i.e. `next start`), and
  // Next.js only *warns* about standalone there ("next start does not work with
  // output: standalone") - it still serves fine. Standalone's dependency
  // tracing buys nothing on SAR anyway: the builder tarballs the whole
  // workspace, node_modules included.
  serverExternalPackages: ["snowflake-sdk"],
};

export default nextConfig;
