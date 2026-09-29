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
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: Anchor, h1: ({ children }) => <h2>{children}</h2>, h2: ({ children }) => <h3>{children}</h3>, h3: ({ children }) => <h4>{children}</h4> }}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
