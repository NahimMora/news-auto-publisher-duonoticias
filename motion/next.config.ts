import type { NextConfig } from "next";

/**
 * Panel editorial local. Se sirve SOLO en 127.0.0.1 (scripts panel/panel:start):
 * no se exponen puertos en produccion.
 */
const nextConfig: NextConfig = {
  // El renderer y el bundler de Remotion usan binarios nativos y webpack/rspack
  // propios: se cargan desde node_modules en tiempo de ejecucion.
  serverExternalPackages: ["@remotion/renderer", "@remotion/bundler", "@remotion/compositor-win32-x64-msvc", "@rspack/core", "esbuild"],
  poweredByHeader: false,
  reactStrictMode: true,
};

export default nextConfig;
