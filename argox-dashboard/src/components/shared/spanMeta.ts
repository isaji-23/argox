// Span-type metadata + derivation from a span's name/attributes.
import type { IconName } from './Icon';

export type SpanType = 'root' | 'llm' | 'tool' | 'processor';

export const SPAN_META: Record<SpanType, { color: string; icon: IconName; label: string }> = {
  root: { color: 'var(--text-secondary)', icon: 'layers', label: 'Root' },
  llm: { color: 'var(--span-llm)', icon: 'llm', label: 'LLM' },
  tool: { color: 'var(--span-tool)', icon: 'tool', label: 'Tool' },
  processor: { color: 'var(--span-processor)', icon: 'processor', label: 'Processor' },
};

/**
 * Infers a span's visual type from its name and OTel attributes.
 *
 * The Collector does not emit an explicit type, so we classify from common
 * GenAI/tool naming: `gen_ai.*` / "llm"/"chat"/"completion" -> llm, names with
 * "tool"/"function" or a `tool.name` attribute -> tool, root spans (no parent)
 * -> root, everything else -> processor.
 */
export function deriveSpanType(
  name: string,
  attributes: Record<string, unknown> | null | undefined,
  hasParent: boolean,
): SpanType {
  const n = (name || '').toLowerCase();
  const attrs = attributes || {};
  const hasAttr = (needle: string) => Object.keys(attrs).some((k) => k.toLowerCase().includes(needle));

  if (!hasParent) return 'root';
  if (n.includes('llm') || n.includes('chat') || n.includes('completion') || hasAttr('gen_ai') || hasAttr('llm')) {
    return 'llm';
  }
  if (n.includes('tool') || n.includes('function') || hasAttr('tool')) return 'tool';
  return 'processor';
}
