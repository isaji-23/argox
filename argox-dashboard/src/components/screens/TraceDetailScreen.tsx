import { useState, useMemo, useEffect, useCallback } from 'react';
import { Icon } from '../shared/Icon';
import { Button } from '../ui/Button';
import { Panel } from '../ui/Panel';
import { WaterfallChart } from '../ui/WaterfallChart';
import { DecisionBadge } from '../shared/DecisionBadge';
import { Badge } from '../ui/Badge';
import { ErrorState } from '../ui/States';
import { api, type SpanDetail } from '../../lib/api';

interface TraceDetailScreenProps {
  traceId?: string;
  onBack: () => void;
}

export function TraceDetailScreen({ traceId, onBack }: TraceDetailScreenProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [spans, setSpans] = useState<SpanDetail[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);

  const fetchTrace = useCallback(async () => {
    if (!traceId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await api.getTrace(traceId);
      setSpans(data.spans);
      setTruncated(data.truncated);
      if (data.spans.length > 0) {
        setSelectedSpanId(data.spans[0].span_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [traceId]);

  useEffect(() => {
    fetchTrace();
  }, [fetchTrace]);

  const traceSummary = useMemo(() => {
    if (spans.length === 0) return null;
    const start = new Date(spans[0].start_time).getTime();
    const end = Math.max(...spans.map(s => new Date(s.end_time).getTime()));
    return {
      id: traceId,
      name: spans[0].name || 'Trace',
      durationMs: end - start,
      agent: spans[0].agent_name || 'unknown',
      model: spans.find(s => s.attributes.model)?.attributes.model || 'unknown',
      startedHuman: new Date(spans[0].start_time).toLocaleString(),
    };
  }, [spans, traceId]);

  const waterfallSpans = useMemo(() => {
    if (spans.length === 0) return [];
    const traceStart = new Date(spans[0].start_time).getTime();
    
    return spans.map(s => {
      const start = new Date(s.start_time).getTime();
      return {
        id: s.span_id,
        parent: s.parent_span_id,
        name: s.name || 'unnamed',
        type: (s.attributes.argox_type as string) || (s.parent_span_id ? 'span' : 'root'),
        t: start - traceStart,
        d: s.duration_ms || 0,
        decision: s.policy_decision || 'allow',
        status: s.run_success === false ? 'error' : 'ok',
        model: s.attributes.model as string,
        tool: s.attributes.tool_name as string,
      };
    });
  }, [spans]);

  const selectedSpan = useMemo(() => 
    spans.find(s => s.span_id === selectedSpanId),
    [selectedSpanId, spans]
  );

  if (loading) return <div className="h-full flex items-center justify-center text-text-muted animate-pulse">Loading trace...</div>;
  if (error || !traceSummary) return (
    <div className="p-10">
      <ErrorState title="Failed to load trace" body={error || 'Trace not found'} onRetry={fetchTrace} />
      <Button variant="ghost" className="mt-4" onClick={onBack}>Back to Traces</Button>
    </div>
  );

  return (
    <div className="flex flex-col h-full bg-bg-base animate-in fade-in duration-500">
      {/* Sub-header / Toolbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-border bg-surface shadow-sm">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={onBack} icon="chevronLeft">
            Back to Traces
          </Button>
          <div className="h-4 w-[1px] bg-border mx-1" />
          <div className="flex items-center gap-3">
            <span className="font-mono text-xs text-text-muted select-all cursor-copy px-2 py-0.5 bg-surface-2 rounded border border-border-faint">
              {traceSummary.id}
            </span>
            <h1 className="font-display font-bold text-lg leading-tight tracking-tight">
              {traceSummary.name}
            </h1>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {truncated && <Badge tone="warn">Truncated</Badge>}
          <Button variant="outline" size="sm" icon="share">Share</Button>
          <Button variant="outline" size="sm" icon="download">Export</Button>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-hidden flex flex-col p-6 gap-6">
        <div className="grid grid-cols-12 gap-6 h-full min-h-0">
          {/* Main Content: Waterfall and Logs */}
          <div className="col-span-8 flex flex-col gap-6 min-h-0">
            <Panel title="Trace Waterfall" icon="traces" className="flex-[3] min-h-0">
              <WaterfallChart 
                spans={waterfallSpans} 
                totalDuration={traceSummary.durationMs} 
                selectedSpanId={selectedSpanId}
                onSelectSpan={setSelectedSpanId}
              />
            </Panel>
            
            <Panel title="Execution Details (Run Records)" className="flex-[2] min-h-0 overflow-hidden">
              <div className="h-full flex flex-col min-h-0 items-center justify-center text-text-muted text-sm">
                <Icon name="info" className="mb-2 opacity-50" />
                Run record content available via DASH-05
              </div>
            </Panel>
          </div>

          {/* Sidebar: Metadata and Policy Violations */}
          <div className="col-span-4 flex flex-col gap-6 overflow-y-auto pr-1">
            {/* Selected Span Details */}
            {selectedSpan && (
              <Panel title="Span Details" accent="accent" icon="layers">
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-text-muted">ID: {selectedSpan.span_id}</span>
                    <DecisionBadge decision={(selectedSpan.policy_decision as any) || 'allow'} size="sm" />
                  </div>
                  <h3 className="font-bold text-md text-text-primary">{selectedSpan.name}</h3>
                  <div className="grid grid-cols-2 gap-2 mt-4">
                    <DetailBox label="Type" value={(selectedSpan.attributes.argox_type as string || 'span').toUpperCase()} />
                    <DetailBox label="Duration" value={selectedSpan.duration_ms != null ? `${selectedSpan.duration_ms.toFixed(1)}ms` : '-'} />
                    {selectedSpan.attributes.model && <DetailBox label="Model" value={selectedSpan.attributes.model as string} />}
                    {selectedSpan.attributes.tool_name && <DetailBox label="Tool" value={selectedSpan.attributes.tool_name as string} />}
                  </div>
                </div>
              </Panel>
            )}

            <Panel title="Metadata" icon="info">
              <div className="space-y-4">
                <MetaItem label="Agent" value={traceSummary.agent} icon="agent" />
                <MetaItem label="Model" value={traceSummary.model} icon="brain" />
                <MetaItem label="Started At" value={traceSummary.startedHuman} />
                <MetaItem label="Total Duration" value={`${traceSummary.durationMs.toFixed(1)}ms`} />
              </div>
            </Panel>

            <Panel title="Attributes" collapsible defaultCollapsed>
              <div className="space-y-2">
                {selectedSpan && Object.entries(selectedSpan.attributes).map(([k, v]) => (
                  <div key={k} className="flex flex-col gap-0.5 border-b border-border-faint pb-1 mb-1 last:border-0">
                    <span className="text-[10px] font-bold text-text-muted uppercase tracking-tighter">{k}</span>
                    <span className="text-xs font-mono text-text-secondary break-all">{JSON.stringify(v)}</span>
                  </div>
                ))}
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

function DetailBox({ label, value }: { label: string, value: string }) {
  return (
    <div className="bg-surface-2 p-2 rounded border border-border-faint">
      <div className="text-[9px] uppercase font-bold tracking-widest text-text-muted mb-0.5">{label}</div>
      <div className="text-xs font-mono text-text-primary truncate">{value}</div>
    </div>
  );
}

function MetaItem({ label, value, icon }: { label: string, value: string, icon?: string }) {
  return (
    <div className="flex items-center justify-between text-sm py-1 border-b border-border-faint last:border-0">
      <span className="text-text-muted flex items-center gap-2">
        {icon && <Icon name={icon} size={14} />}
        {label}
      </span>
      <span className="text-text-primary font-medium">{value}</span>
    </div>
  );
}
