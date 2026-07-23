// CredentialInjector for query_key auth strategy.
// Injects credential into an allowlisted query parameter name.
// Strips any worker-supplied copy of the parameter.
export function makeQueryKeyInjector(paramName: string = "api_key") {
  return async (input: {
    request: Request
    upstream: URL
    credential: { secret: string }
  }): Promise<Request> => {
    const { request, credential } = input
    const url = new URL(request.url)
    // Strip any existing copy
    url.searchParams.delete(paramName)
    // Inject server-side credential
    url.searchParams.set(paramName, credential.secret)
    const headers = new Headers(request.headers)
    return new Request(url.toString(), { method: request.method, headers, body: request.body })
  }
}
