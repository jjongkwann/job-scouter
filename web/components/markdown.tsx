import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AnchorHTMLAttributes } from 'react'

function Anchor({ href, children, ...props }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const safe = href && /^https?:/.test(href) ? href : '#'
  return (
    <a href={safe} target="_blank" rel="noopener" {...props}>
      {children}
    </a>
  )
}

export function Markdown({ text }: { text: string }) {
  return (
    <div className="doc">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: Anchor }}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
