export function preserveHighlightedCodeLanguage(html: string, language: string | undefined) {
  const value = language?.toLowerCase()
  if (!value || !/^[a-z0-9_+-]+$/.test(value)) return html
  return html.replace("<code>", `<code class="language-${value}">`)
}
