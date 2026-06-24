import { cn } from "@/lib/utils";

// Shared status vocabulary — glyph + color identical to the TUI
// (agenthook/tui.py:55-68 and design-system/README.md). Meaning survives in
// mono because every state pairs a glyph with a color.
const JOB: Record<string, { glyph: string; color: string }> = {
  queued: { glyph: "·", color: "text-brand-stone" },
  running: { glyph: "▸", color: "text-brand-amber" },
  awaiting_approval: { glyph: "◷", color: "text-brand-lilac" },
  success: { glyph: "✓", color: "text-brand-sage" },
  "failed-checks": { glyph: "▲", color: "text-brand-clay" },
  blocked: { glyph: "▲", color: "text-brand-clay" },
  error: { glyph: "✗", color: "text-brand-rust" },
  timeout: { glyph: "✗", color: "text-brand-rust" },
  interrupted: { glyph: "⊘", color: "text-brand-stone" },
  rejected: { glyph: "✗", color: "text-brand-stone" },
  expired: { glyph: "·", color: "text-brand-stone" },
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const s = JOB[status] ?? { glyph: "·", color: "text-muted-foreground" };
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-sm", s.color, className)}>
      <span aria-hidden>{s.glyph}</span>
      {status}
    </span>
  );
}

export function InstanceState({ paused, className }: { paused: boolean; className?: string }) {
  return paused ? (
    <span className={cn("inline-flex items-center gap-1.5 text-sm text-brand-stone", className)}>
      <span aria-hidden>⏸</span>paused
    </span>
  ) : (
    <span className={cn("inline-flex items-center gap-1.5 text-sm text-brand-sage", className)}>
      <span aria-hidden>●</span>active
    </span>
  );
}
