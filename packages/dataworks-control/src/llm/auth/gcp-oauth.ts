// STUB: GCP OAuth credential injector.
// Full flow requires service account JSON or Application Default Credentials.
// Obtains and caches short-lived access tokens server-side.
// This stub exposes the CredentialInjector interface but logs that real OAuth needs staging credentials.
export function makeGcpOAuthInjector() {
  return async (input: {
    request: Request
    upstream: URL
    credential: { secret: string }
  }): Promise<Request> => {
    // STUB: In production, this would:
    // 1. Use gtoken or google-auth-library to obtain OAuth2 access token
    // 2. Cache the token with TTL (typically 1 hour)
    // 3. Inject "authorization: Bearer <token>" header
    // Requires: staging service account JSON or ADC credentials
    console.warn("[gcp-oauth] STUB: real OAuth requires staging GCP service account credentials")
    return input.request
  }
}
