import type { ReactNode } from 'react'

/** Minimal markdown for our own research docs: headings, paragraphs, bullet lists, pipe tables, inline code/bold. No deps. */
export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const out: ReactNode[] = []
  let i = 0, key = 0
  const inline = (s: string): ReactNode[] => {
    const parts: ReactNode[] = []
    const re = /(`[^`]+`|\*\*[^*]+\*\*)/g
    let last = 0, m: RegExpExecArray | null
    while ((m = re.exec(s))) {
      if (m.index > last) parts.push(s.slice(last, m.index))
      const t = m[0]
      parts.push(t.startsWith('`') ? <code key={key++} className="mono">{t.slice(1, -1)}</code> : <b key={key++}>{t.slice(2, -2)}</b>)
      last = m.index + t.length
    }
    if (last < s.length) parts.push(s.slice(last))
    return parts
  }
  while (i < lines.length) {
    const l = lines[i]
    if (!l.trim()) { i++; continue }
    const h = /^(#{1,3})\s+(.*)/.exec(l)
    if (h) { const lvl = h[1].length; out.push(lvl === 1 ? <h1 key={key++} style={{ fontSize: 18 }}>{inline(h[2])}</h1> : lvl === 2 ? <h2 key={key++} style={{ fontSize: 15, marginTop: 18 }}>{inline(h[2])}</h2> : <h3 key={key++} style={{ fontSize: 13, marginTop: 12 }}>{inline(h[2])}</h3>); i++; continue }
    if (l.startsWith('|')) {
      const rows: string[][] = []
      while (i < lines.length && lines[i].startsWith('|')) { rows.push(lines[i].split('|').slice(1, -1).map(c => c.trim())); i++ }
      const body = rows.filter(r => !r.every(c => /^:?-{2,}:?$/.test(c)))
      const [head, ...rest] = body
      out.push(<div key={key++} style={{ overflowX: 'auto', margin: '8px 0' }}><table className="tbl" style={{ fontSize: 12 }}>
        <thead><tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead>
        <tbody>{rest.map((r, ri) => <tr key={ri} className={r.includes('PASS') ? 'pos-row' : ''}>{r.map((c, j) => <td key={j} className={/^-?[\d.%]+/.test(c) || c.startsWith('{') ? 'mono' : ''} style={c === 'PASS' ? { color: 'var(--pos)', fontWeight: 600 } : c === 'fail' ? { color: 'var(--mut)' } : undefined}>{inline(c)}</td>)}</tr>)}</tbody>
      </table></div>)
      continue
    }
    if (/^\s*[-*]\s+/.test(l)) {
      const items: string[] = []
      while (i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || (/^\s{2,}\S/.test(lines[i]) && items.length))) {
        if (/^\s*[-*]\s+/.test(lines[i])) items.push(lines[i].replace(/^\s*[-*]\s+/, '')); else items[items.length - 1] += ' ' + lines[i].trim()
        i++
      }
      out.push(<ul key={key++} style={{ margin: '6px 0 6px 18px', fontSize: 13, lineHeight: 1.5 }}>{items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ul>)
      continue
    }
    if (/^\d+\.\s+/.test(l)) {
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) { items.push(lines[i].replace(/^\d+\.\s+/, '')); i++ }
      out.push(<ol key={key++} style={{ margin: '6px 0 6px 18px', fontSize: 13, lineHeight: 1.5 }}>{items.map((it, j) => <li key={j}>{inline(it)}</li>)}</ol>)
      continue
    }
    const para: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(#{1,3})\s|^\||^\s*[-*]\s+|^\d+\.\s+/.test(lines[i])) { para.push(lines[i].trim()); i++ }
    out.push(<p key={key++} style={{ fontSize: 13, lineHeight: 1.55, margin: '6px 0' }}>{inline(para.join(' '))}</p>)
  }
  return <div>{out}</div>
}
