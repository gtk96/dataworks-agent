/**
 * Markdown rendering utility with syntax highlighting support.
 * Uses markdown-it for parsing and DOMPurify for sanitization.
 */

import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
})

export interface RenderedMarkdown {
  html: string
}

export function renderMarkdown(text: string): RenderedMarkdown {
  if (!text || !text.trim()) {
    return { html: '<p class="empty-message"></p>' }
  }

  const rawHtml = md.render(text)
  const sanitized = DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'em', 'u', 's', 'code', 'pre',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li',
      'a', 'blockquote',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'div', 'span', 'hr',
    ],
    ALLOWED_ATTR: ['href', 'class', 'target', 'rel'],
  })

  return { html: sanitized }
}

/**
 * Typewriter effect: progressively reveals markdown content.
 * Yields chunks of rendered HTML at a given speed.
 */
export async function* typewriterEffect(
  text: string,
  chunkSize: number = 20,
  delayMs: number = 16,
): AsyncGenerator<string> {
  let accumulated = ''
  const chars = text.split('')

  for (let i = 0; i < chars.length; i += chunkSize) {
    accumulated += chars.slice(i, i + chunkSize).join('')
    const { html } = renderMarkdown(accumulated)
    yield html

    if (i + chunkSize < chars.length) {
      await new Promise((resolve) => setTimeout(resolve, delayMs))
    }
  }

  // Final render
  yield renderMarkdown(text).html
}
