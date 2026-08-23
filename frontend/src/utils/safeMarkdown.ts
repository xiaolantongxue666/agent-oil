import { marked } from 'marked'

marked.setOptions({
  breaks: true,
  gfm: true,
})

const ALLOWED_TAGS = new Set([
  'A', 'BLOCKQUOTE', 'BR', 'CODE', 'EM', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
  'HR', 'LI', 'OL', 'P', 'PRE', 'STRONG', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD',
  'TR', 'UL',
])
const ALLOWED_HREF = /^(https?:|mailto:|\/|#)/i

/** 将知识原文渲染为安全、受限的 Markdown HTML，禁止内联 HTML 和事件属性。 */
export function renderSafeMarkdown(text: string): string {
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const document = new DOMParser().parseFromString(marked.parse(escaped) as string, 'text/html')

  for (const element of Array.from(document.body.querySelectorAll('*'))) {
    if (!ALLOWED_TAGS.has(element.tagName)) {
      element.replaceWith(document.createTextNode(element.textContent || ''))
      continue
    }
    for (const attribute of Array.from(element.attributes)) {
      const isSafeLink = element.tagName === 'A'
        && attribute.name.toLowerCase() === 'href'
        && ALLOWED_HREF.test(attribute.value)
      if (!isSafeLink) element.removeAttribute(attribute.name)
    }
    if (element.tagName === 'A') {
      element.setAttribute('rel', 'noopener noreferrer')
      element.setAttribute('target', '_blank')
    }
  }
  return document.body.innerHTML
}
