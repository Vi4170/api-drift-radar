import type { SchemaChange, SchemaNode } from '../api/types'
import { humanize } from '../utils/format'
import { SeverityBadge } from './ui'

export function SchemaDiffTable({ changes }: { changes: SchemaChange[] }) {
  if (changes.length === 0) {
    return <p className="muted">No differences between the approved baseline and the latest response.</p>
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <caption className="sr-only">Schema differences</caption>
        <thead>
          <tr>
            <th scope="col">Severity</th>
            <th scope="col">JSON path</th>
            <th scope="col">Change</th>
            <th scope="col">Baseline type</th>
            <th scope="col">Observed type</th>
            <th scope="col">Description</th>
          </tr>
        </thead>
        <tbody>
          {changes.map((c) => (
            <tr key={`${c.path}-${c.rule}`}>
              <td>
                <SeverityBadge severity={c.severity} />
              </td>
              <td>
                <code>{c.path}</code>
              </td>
              <td>{humanize(c.kind)}</td>
              <td>
                <code className="type-old">{c.old ?? '—'}</code>
              </td>
              <td>
                <code className="type-new">{c.new ?? '—'}</code>
              </td>
              <td>{c.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function typeLabel(node: SchemaNode): string {
  let label = node.type === 'mixed' ? (node.types ?? []).join(' | ') : node.type
  if (node.type === 'array') label = `array<${node.items ? typeLabel(node.items) : 'unknown'}>`
  if (node.nullable && node.type !== 'null') label += ' | null'
  return label
}

/** Read-only tree rendering of an inferred schema; changed paths are highlighted. */
export function SchemaTree({
  node,
  highlight = new Map(),
  path = '$',
  name = 'root',
  optional = false,
}: {
  node: SchemaNode
  highlight?: Map<string, SchemaChange['severity']>
  path?: string
  name?: string
  optional?: boolean
}) {
  const severity = highlight.get(path)
  const children: [string, SchemaNode, string, boolean][] = []
  if (node.type === 'object' && node.properties) {
    const required = new Set(node.required ?? [])
    for (const [key, child] of Object.entries(node.properties).sort(([a], [b]) => a.localeCompare(b))) {
      const childPath = /^[A-Za-z_][A-Za-z0-9_]*$/.test(key) ? `${path}.${key}` : `${path}["${key}"]`
      children.push([key, child, childPath, !required.has(key)])
    }
  } else if (node.type === 'array' && node.items) {
    children.push(['[*]', node.items, `${path}[*]`, false])
  }
  return (
    <li className={severity ? `tree-node tree-${severity}` : 'tree-node'}>
      <span className="tree-key">{name}</span>
      {optional && <span className="tree-optional">?</span>}
      <span className="tree-type">{typeLabel(node)}</span>
      {children.length > 0 && (
        <ul>
          {children.map(([key, child, childPath, opt]) => (
            <SchemaTree key={childPath} node={child} name={key} path={childPath} optional={opt} highlight={highlight} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function SchemaPanel({
  title,
  schema,
  changes,
  empty,
}: {
  title: string
  schema: SchemaNode | null
  changes: SchemaChange[]
  empty: string
}) {
  const highlight = new Map(changes.map((c) => [c.path, c.severity] as const))
  return (
    <section className="card schema-panel" aria-label={title}>
      <h3>{title}</h3>
      {schema ? (
        <ul className="tree">
          <SchemaTree node={schema} highlight={highlight} />
        </ul>
      ) : (
        <p className="muted">{empty}</p>
      )}
    </section>
  )
}
