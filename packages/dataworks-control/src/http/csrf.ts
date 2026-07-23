export function checkOrigin(request: Request, publicOrigin: string): boolean {
  const origin = request.headers.get("origin")
  if (origin) {
    if (origin === publicOrigin) return true
    // Local demo: Vite frontend (3000) proxies to control plane (8084).
    // Allow only loopback Vite origins when control plane is also loopback.
    try {
      const o = new URL(origin)
      const p = new URL(publicOrigin)
      const loopback = (h: string) => h === "127.0.0.1" || h === "localhost"
      if (
        process.env.NODE_ENV !== "production" &&
        loopback(o.hostname) &&
        loopback(p.hostname) &&
        (o.port === "3000" || o.port === "5173")
      ) {
        return true
      }
    } catch {
      return false
    }
    return false
  }

  const secFetchSite = request.headers.get("sec-fetch-site")
  return secFetchSite === "same-origin" || secFetchSite === "none"
}

export function getClientIP(request: Request): string {
  return (
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-real-ip") ||
    "unknown"
  )
}
