import { cn } from '../../lib/utils';
import { Icon } from '../shared/Icon';

interface Span {
  id: string;
  parent: string | null;
  name: string;
  type: string;
  t: number; // offset in ms
  d: number; // duration in ms
  decision: string;
  status: string;
  model?: string;
  tool?: string;
}

interface WaterfallChartProps {
  spans: Span[];
  totalDuration: number;
  selectedSpanId?: string | null;
  onSelectSpan: (id: string) => void;
}

export function WaterfallChart({ spans, totalDuration, selectedSpanId, onSelectSpan }: WaterfallChartProps) {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Time axis header */}
      <div className="flex border-b border-border bg-surface-2 px-2 py-1 text-[10px] font-mono text-text-muted">
        <div className="w-1/3 border-r border-border px-2">Operation</div>
        <div className="flex-1 px-2 relative h-4">
          <div className="absolute left-0 top-0 h-full border-l border-border-faint" />
          <div className="absolute left-1/4 top-0 h-full border-l border-border-faint" />
          <div className="absolute left-1/2 top-0 h-full border-l border-border-faint" />
          <div className="absolute left-3/4 top-0 h-full border-l border-border-faint" />
          <div className="absolute right-0 top-0 h-full border-r border-border-faint" />
          
          <span className="absolute left-0 top-0 ml-1">0ms</span>
          <span className="absolute right-0 top-0 mr-1">{totalDuration}ms</span>
        </div>
      </div>

      {/* Waterfall Body */}
      <div className="flex-1 overflow-y-auto min-h-0 bg-bg-base/50">
        {spans.map((span, idx) => {
          const safeTotal = totalDuration || 1;
          const left = (span.t / safeTotal) * 100;
          const width = Math.max((span.d / safeTotal) * 100, 0.5);
          const isSelected = selectedSpanId === span.id;
          
          return (
            <div 
              key={span.id} 
              onClick={() => onSelectSpan(span.id)}
              className={cn(
                "flex items-center cursor-pointer hover:bg-surface-3 transition-colors group border-b border-border-faint/30",
                isSelected ? "bg-accent-surface border-l-2 border-l-accent" : (idx === 0 && "bg-surface-2/30")
              )}
            >
              {/* Span Label */}
              <div className="w-1/3 border-r border-border/50 py-2 px-3 flex items-center gap-2 overflow-hidden">
                <SpanIcon type={span.type} />
                <span className={cn(
                  "truncate text-xs font-medium",
                  span.decision === 'block' ? "text-block-bright" : (isSelected ? "text-accent" : "text-text-primary")
                )}>
                  {span.name}
                </span>
              </div>

              {/* Visualization bar */}
              <div className="flex-1 relative h-8 px-2 flex items-center">
                {/* Vertical grid lines */}
                <div className="absolute inset-0 flex justify-between pointer-events-none opacity-20">
                  <div className="w-[1px] bg-border-faint h-full" />
                  <div className="w-[1px] bg-border-faint h-full" />
                  <div className="w-[1px] bg-border-faint h-full" />
                  <div className="w-[1px] bg-border-faint h-full" />
                  <div className="w-[1px] bg-border-faint h-full" />
                </div>

                {/* The bar */}
                <div 
                  className={cn(
                    "h-3 rounded-sm relative shadow-sm transition-all group-hover:brightness-110",
                    getSpanColorClass(span.type, span.decision)
                  )}
                  style={{ 
                    left: `${left}%`, 
                    width: `${width}%`,
                    minWidth: '2px'
                  }}
                >
                  {/* Duration label inside or beside */}
                  <span className="absolute left-full ml-2 text-[10px] font-mono text-text-muted opacity-0 group-hover:opacity-100 whitespace-nowrap">
                    {span.d}ms
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SpanIcon({ type }: { type: string }) {
  switch (type) {
    case 'llm': return <Icon name="brain" size={13} className="text-span-llm" />;
    case 'tool': return <Icon name="tool" size={13} className="text-span-tool" />;
    case 'processor': return <Icon name="cpu" size={13} className="text-span-processor" />;
    case 'root': return <Icon name="play" size={13} className="text-text-muted" />;
    default: return <Icon name="circle" size={13} className="text-text-faint" />;
  }
}

function getSpanColorClass(type: string, decision: string) {
  if (decision === 'block') return "bg-block border border-block-border";
  
  switch (type) {
    case 'llm': return "bg-[var(--span-llm)]";
    case 'tool': return "bg-[var(--span-tool)]";
    case 'processor': return "bg-[var(--span-processor)]";
    case 'root': return "bg-surface-3 border border-border-strong";
    default: return "bg-surface-3";
  }
}
