// git diff 원문에 색만 입힌다 — web.py `_color_diff`와 같은 규칙(+++/--- 헤더 줄은 제외).

function color(ln: string): string | undefined {
  if (ln.startsWith('+') && !ln.startsWith('+++')) return 'var(--good)'
  if (ln.startsWith('-') && !ln.startsWith('---')) return 'var(--bad)'
  return undefined
}

export function Diff({ diff }: { diff: string }) {
  return (
    <pre className="m-0 mt-2 overflow-x-auto font-mono text-[11.5px] leading-[1.5]">
      {diff.split('\n').map((ln, i) => (
        <span key={i} style={{ color: color(ln) }}>
          {ln}
          {'\n'}
        </span>
      ))}
    </pre>
  )
}
