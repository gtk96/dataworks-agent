import { sentryVitePlugin } from "@sentry/vite-plugin"
import { defineConfig } from "vite"
import desktopPlugin from "./vite"

const sentry =
  process.env.SENTRY_AUTH_TOKEN && process.env.SENTRY_ORG && process.env.SENTRY_PROJECT
    ? sentryVitePlugin({
        authToken: process.env.SENTRY_AUTH_TOKEN,
        org: process.env.SENTRY_ORG,
        project: process.env.SENTRY_PROJECT,
        telemetry: false,
        release: {
          name: process.env.SENTRY_RELEASE ?? process.env.VITE_SENTRY_RELEASE,
        },
        sourcemaps: {
          assets: "./dist/**",
          filesToDeleteAfterUpload: "./dist/**/*.map",
        },
      })
    : false

export default defineConfig({
  plugins: [desktopPlugin, sentry] as any,
  server: {
    host: "0.0.0.0",
    allowedHosts: true,
    port: 3000,
    // Local DataWorks Agent demo: browser UI talks to control-plane APIs.
    // Keep Origin as the browser origin (http://127.0.0.1:3000) so CSRF same-origin
    // checks can be relaxed by proxy header rewrite only when needed.
    proxy: {
      "/api": {
        target: process.env.DATAWORKS_CONTROL_URL ?? "http://127.0.0.1:8084",
        changeOrigin: false,
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            // Preserve browser Origin for audit; also pass a same-origin fallback header.
            const origin = req.headers.origin
            if (origin) proxyReq.setHeader("origin", origin)
            // Some control-plane paths require exact publicOrigin; for local demo
            // rewrite to backend origin only if request has no Origin (non-browser).
            if (!origin) proxyReq.setHeader("origin", process.env.DATAWORKS_CONTROL_URL ?? "http://127.0.0.1:8084")
          })
        },
      },
      "/opencode": {
        target: process.env.DATAWORKS_CONTROL_URL ?? "http://127.0.0.1:8084",
        changeOrigin: false,
        ws: true,
      },
      "/internal": {
        target: process.env.DATAWORKS_CONTROL_URL ?? "http://127.0.0.1:8084",
        changeOrigin: false,
      },
    },
  },
  build: {
    target: "esnext",
    sourcemap: true,
  },
})
