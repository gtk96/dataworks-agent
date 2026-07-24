import { expect, test } from "bun:test"
import { preserveHighlightedCodeLanguage } from "./marked-code-language"

test("preserves a safe fenced language on highlighted code", () => {
  expect(preserveHighlightedCodeLanguage('<pre class="shiki"><code><span>SELECT</span></code></pre>', "SQL")).toBe(
    '<pre class="shiki"><code class="language-sql"><span>SELECT</span></code></pre>',
  )
})

test("does not inject unsafe fenced language metadata", () => {
  expect(preserveHighlightedCodeLanguage("<pre><code>text</code></pre>", 'sql\" onclick=\"alert(1)')).toBe(
    "<pre><code>text</code></pre>",
  )
})
