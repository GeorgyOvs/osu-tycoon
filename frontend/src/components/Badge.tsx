const TIERS: Record<string, { from: string; to: string; ring: string; label: string }> = {
  community: { from: '#3b82f6', to: '#1e3a8a', ring: '#93c5fd', label: 'CUP' },
  open: { from: '#10b981', to: '#064e3b', ring: '#6ee7b7', label: 'OPEN' },
  major: { from: '#f59e0b', to: '#78350f', ring: '#fde68a', label: 'MAJOR' },
  owc: { from: '#ef4444', to: '#7f1d1d', ring: '#fecaca', label: 'OWC' },
  clan: { from: '#a855f7', to: '#4c1d95', ring: '#e9d5ff', label: 'CLAN' },
}

function tierOf(name: string, tier?: string) {
  if (tier && TIERS[tier]) return TIERS[tier]
  const n = name.toLowerCase()
  if (n.includes('world cup') || n.includes('owc')) return TIERS.owc
  if (n.includes('major') || n.includes('invitational') || n.includes('corsace') || n.includes('roundtable')) return TIERS.major
  if (n.includes('open')) return TIERS.open
  if (n.includes('clan')) return TIERS.clan
  return TIERS.community
}

function initials(name: string) {
  const words = name.replace(/\b\d{4}\b/g, '').split(/[\s:]+/).filter((w) => /[a-z0-9]/i.test(w) && !/^(the|of|osu!?|cup)$/i.test(w))
  return (words.length ? words : [name]).slice(0, 3).map((w) => w[0].toUpperCase()).join('')
}

/** An osu!-style tournament badge: 86x40, banner colours by tier, the tournament's initials and year. */
export function TournamentBadge({ name, date, tier }: { name: string; date: string; tier?: string }) {
  const c = tierOf(name, tier)
  const year = date.slice(0, 4)
  const id = `bd${Math.abs([...name].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) | 0, 7))}`
  return (
    <svg viewBox="0 0 86 40" width={86} height={40} role="img" aria-label={`${name} (${year})`} className="rounded-[4px] shadow-md shadow-black/40">
      <title>{`${name} · ${date}`}</title>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={c.from} />
          <stop offset="1" stopColor={c.to} />
        </linearGradient>
      </defs>
      <rect width="86" height="40" rx="4" fill={`url(#${id})`} />
      <path d="M0 28 L86 12 V40 H0Z" fill="#000" opacity="0.18" />
      <rect x="1" y="1" width="84" height="38" rx="3.2" fill="none" stroke={c.ring} strokeOpacity="0.55" />
      <text x="8" y="22" fontSize="15" fontWeight="800" fill="#fff" fontFamily="Torus, 'Segoe UI', sans-serif" letterSpacing="0.5">
        {initials(name)}
      </text>
      <text x="8" y="34" fontSize="7" fontWeight="700" fill={c.ring} fontFamily="Torus, 'Segoe UI', sans-serif" letterSpacing="1">
        {c.label}
      </text>
      <text x="79" y="34" fontSize="9" fontWeight="800" fill="#fff" textAnchor="end" fontFamily="Torus, 'Segoe UI', sans-serif">
        {year}
      </text>
      <path d="M72 6l1.9 3.9 4.3.6-3.1 3 .7 4.2-3.8-2-3.8 2 .7-4.2-3.1-3 4.3-.6z" fill="#fff" opacity="0.9" />
    </svg>
  )
}
