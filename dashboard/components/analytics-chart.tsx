"use client";

import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function TrendChart({
  data,
}: {
  data: Array<{ date: string; safe: number; suspicious: number; malicious: number; needs_review: number }>;
}) {
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id="safeFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="5%" stopColor="#22c55e" stopOpacity={0.5} />
              <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="suspiciousFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.5} />
              <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="maliciousFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="5%" stopColor="#ef4444" stopOpacity={0.5} />
              <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="needsReviewFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="5%" stopColor="#38bdf8" stopOpacity={0.45} />
              <stop offset="95%" stopColor="#38bdf8" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="rgba(148,163,184,0.14)" vertical={false} />
          <XAxis dataKey="date" stroke="#94a3b8" />
          <YAxis stroke="#94a3b8" />
          <Tooltip />
          <Area type="monotone" dataKey="safe" stroke="#22c55e" fill="url(#safeFill)" />
          <Area type="monotone" dataKey="suspicious" stroke="#f59e0b" fill="url(#suspiciousFill)" />
          <Area type="monotone" dataKey="needs_review" stroke="#38bdf8" fill="url(#needsReviewFill)" />
          <Area type="monotone" dataKey="malicious" stroke="#ef4444" fill="url(#maliciousFill)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SignalBarChart({
  data,
}: {
  data: Array<{ name: string; count: number }>;
}) {
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical">
          <CartesianGrid stroke="rgba(148,163,184,0.14)" horizontal={false} />
          <XAxis type="number" stroke="#94a3b8" />
          <YAxis type="category" dataKey="name" width={140} stroke="#94a3b8" />
          <Tooltip />
          <Bar dataKey="count" fill="#38bdf8" radius={[0, 8, 8, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
