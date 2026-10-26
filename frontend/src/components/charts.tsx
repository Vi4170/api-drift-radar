import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export interface LatencyDatum {
  time: string
  latency: number | null
}

const timeFmt = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

export function LatencyChart({ data, label }: { data: LatencyDatum[]; label: string }) {
  if (data.every((d) => d.latency === null)) {
    return <p className="muted">No latency data in this window yet.</p>
  }
  return (
    <figure className="chart" aria-label={label}>
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="latencyFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" vertical={false} />
          <XAxis dataKey="time" tickFormatter={timeFmt} stroke="var(--text-muted)" fontSize={12} minTickGap={32} />
          <YAxis stroke="var(--text-muted)" fontSize={12} width={56} unit=" ms" />
          <Tooltip
            contentStyle={{ background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 8 }}
            labelFormatter={(v) => new Date(String(v)).toLocaleString()}
            formatter={(v) => [`${Math.round(Number(v))} ms`, 'Latency']}
          />
          <Area
            type="monotone"
            dataKey="latency"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#latencyFill)"
            connectNulls
            dot={{ r: 3, fill: 'var(--accent)', strokeWidth: 0 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
      <figcaption className="sr-only">{label}</figcaption>
    </figure>
  )
}
