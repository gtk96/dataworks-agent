// CredentialInjector for static_header auth strategy.
// Supports: bearer, x-api-key, basic, or named static header injection.
// Input credential.secret is the raw credential value.
// Input credential.headerName for named headers.
// Input credential.headerScheme determines injection method.
export function makeStaticHeaderInjector() {
  return async (input: {
    request: Request
    upstream: URL
    credential: { secret: string; headerName?: string; headerScheme?: "bearer" | "basic" | "apikey" | "named" }
  }): Promise<Request> => {
    const { request, credential } = input
    const headers = new Headers(request.headers)
    const secret = credential.secret

    if (credential.headerScheme === "basic") {
      headers.set("authorization", `Basic ${Buffer.from(secret).toString("base64")}`)
    } else if (credential.headerScheme === "apikey" && credential.headerName) {
      headers.set(credential.headerName, secret)
    } else if (credential.headerScheme === "named" && credential.headerName) {
      headers.set(credential.headerName, secret)
    } else {
      // Default: bearer
      headers.set("authorization", `Bearer ${secret}`)
    }

    return new Request(request.url, { method: request.method, headers, body: request.body })
  }
}
