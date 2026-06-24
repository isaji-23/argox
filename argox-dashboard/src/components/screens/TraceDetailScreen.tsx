import { useState, useMemo, useEffect, useCallback } from 'react';
import { Icon } from '../shared/Icon';
import { Button } from '../ui/Button';
import { Panel } from '../ui/Panel';
import { WaterfallChart } from '../ui/WaterfallChart';
import { DecisionBadge } from '../shared/DecisionBadge';
import { Badge } from '../ui/Badge';
import { ErrorState } from '../ui/States';
import { api, type SpanDetail, type RunDetail, APIError } from '../../lib/api';

interface TraceDetailScreenProps {
  traceId?: string;
  onBack: () => void;
}

export function TraceDetailScreen({ traceId, onBack }: TraceDetailScreenProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [spans, setSpans] = useState<SpanDetail[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loadingRun, setLoadingRun] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [retryTrigger, setRetryTrigger] = useState(0);

  useEffect(() => {
    let ignore = false;

    if (!traceId) {
      setSpans([]);
      setRun(null);
      setLoading(false);
      setLoadingRun(false);
      return;
    }

    const fetchTraceData = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await api.getTrace(traceId);
        if (!ignore) {
          setSpans(data.spans);
          setTruncated(data.truncated);
          setDurationMs(data.duration_ms);
          if (data.spans.length > 0) {
            setSelectedSpanId(data.spans[0].span_id);
          }
        }
      } catch (err) {
        if (!ignore) {
          setError(err instanceof Error ? err.message : 'Unknown error');
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    const fetchRunData = async () => {
      setLoadingRun(true);
      setRunError(null);
      try {
        const data = await api.getRunByTrace(traceId);
        if (!ignore) {
          setRun(data);
        }
      } catch (err) {
        if (!ignore) {
          if (err instanceof APIError && err.status === 404) {
            setRun(null);
          } else {
            setRunError(err instanceof Error ? err.message : 'Failed to load run record');
            setRun(null);
          }
        }
      } finally {
        if (!ignore) {
          setLoadingRun(false);
        }
      }
    };

    fetchTraceData();
    fetchRunData();

    return () => {
      ignore = true;
    };
  }, [traceId, retryTrigger]);

  const handleRetry = useCallback(() => {
    setRetryTrigger(prev => prev + 1);
  }, []);

  const traceSummary = useMemo(() => {
    if (spans.length === 0) return null;
    let finalDurationMs = durationMs;
    if (finalDurationMs === null || finalDurationMs === undefined) {
      const start = new Date(spans[0].start_time).getTime();
      const endTimes = spans
        .map(s => s.end_time ? new Date(s.end_time).getTime() : null)
        .filter((t): t is number => t !== null && !isNaN(t));
      const end = endTimes.length > 0 ? Math.max(...endTimes) : start;
      finalDurationMs = end - start;
    }
    return {
      id: traceId,
      name: spans[0].name || 'Trace',
      durationMs: finalDurationMs,
      agent: spans[0].agent_name || 'unknown',
      model: spans.find(s => s.attributes.model)?.attributes.model || 'unknown',
      startedHuman: new Date(spans[0].start_time).toLocaleString(),
    };
  }, [spans, traceId, durationMs]);

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
      <ErrorState title="Failed to load trace" body={error || 'Trace not found'} onRetry={handleRetry} />
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
              {loadingRun ? (
                <div className="h-full flex items-center justify-center text-text-muted animate-pulse">
                  Loading run record...
                </div>
              ) : !run ? (
                <div className="h-full flex flex-col min-h-[120px] items-center justify-center text-text-muted text-sm p-6 bg-surface-2/30 rounded border border-border border-dashed">
                  <Icon name="info" className="mb-2 opacity-50" size={18} />
                  {runError ? (
                    <span className="text-center font-medium text-block-bright">
                      Failed to load run record: {runError}
                    </span>
                  ) : (
                    <span className="text-center font-medium">
                      no run record available — wire <code className="bg-surface-3 px-1 py-0.5 rounded text-xs">HttpRunExporter</code>
                    </span>
                  )}
                </div>
              ) : (
                <div className="flex-1 overflow-y-auto min-h-0 pr-1">
                  {/* Prompt & Output Collapsible Blocks */}
                  <CollapsibleBlock title="Prompt" content={run.prompt || ''} badge="user content" />
                  <CollapsibleBlock title="Final Output" content={run.final_output || ''} badge="user content" />

                  {/* Policy Violations Section */}
                  {run.policies?.violations && run.policies.violations.length > 0 && (
                    <div className="mb-6">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-block-bright mb-2 flex items-center gap-2">
                        <Icon name="shieldAlert" size={14} className="text-block-bright" />
                        Policy Violations
                      </h4>
                      <div className="border border-block-border rounded bg-block-bg border-l-[2.5px] border-l-block-edge p-3 space-y-2">
                        {run.policies.violations.map((violation, idx) => (
                          <div key={idx} className="flex gap-2 text-xs text-text-primary leading-relaxed">
                            <span className="text-block-bright font-bold">•</span>
                            <span>{violation}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Tool Calls Section */}
                  <div className="mb-6">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary mb-2 flex items-center gap-2">
                      <Icon name="tool" size={14} />
                      Tool Invocations ({run.tools?.called?.length || 0})
                    </h4>
                    {(!run.tools?.called || run.tools.called.length === 0) ? (
                      <div className="text-xs text-text-muted italic py-2">No tools called in this run.</div>
                    ) : (
                      <div className="border border-border rounded overflow-hidden divide-y divide-border bg-surface-2/40">
                        {run.tools.called.map((tool, idx) => (
                          <div key={idx} className="p-3 hover:bg-surface-3/30 transition-colors">
                            <div className="flex items-center justify-between gap-4">
                              <div className="flex items-center gap-2">
                                <span className="font-mono text-xs font-bold text-text-primary">{tool.name}</span>
                                {tool.blocked && (
                                  <span className="text-[10px] bg-block-bg text-block-bright border border-block-border border-l-[2px] border-l-block-edge px-1.5 py-0.5 rounded font-medium flex items-center gap-1">
                                    <Icon name="ban" size={10} />
                                    Blocked
                                  </span>
                                )}
                              </div>
                              <span className="text-xs font-mono text-text-secondary">
                                {tool.duration != null ? `${(tool.duration * 1000).toFixed(0)}ms` : '-'}
                              </span>
                            </div>
                            
                            {tool.blocked && tool.block_reason && (
                              <div className="mt-1.5 text-xs text-block-bright font-medium bg-block-bg p-2 rounded border border-block-border border-l-[2px] border-l-block-edge">
                                Reason: {tool.block_reason}
                              </div>
                            )}

                            {tool.result && (
                              <div className="mt-1.5">
                                <div className="text-[10px] font-bold text-text-muted uppercase mb-0.5">Result Preview</div>
                                <pre className="text-[11px] font-mono text-text-secondary bg-bg-base p-2 rounded border border-border max-h-24 overflow-y-auto whitespace-pre-wrap break-words">
                                  {tool.result}
                                </pre>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Token Tracking Table */}
                  <div className="mb-2">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-text-secondary mb-2 flex items-center gap-2">
                      <Icon name="llm" size={14} />
                      LLM Call Token Consumption
                    </h4>
                    {(!run.tokens?.by_api_call || run.tokens.by_api_call.length === 0) ? (
                      <div className="text-xs text-text-muted italic py-2">No LLM token consumption records.</div>
                    ) : (
                      <div className="border border-border rounded overflow-hidden bg-surface-2/40">
                        <table className="w-full text-left text-xs border-collapse">
                          <thead>
                            <tr className="bg-surface-3/50 border-b border-border text-text-muted uppercase font-bold tracking-wider text-[10px]">
                              <th className="px-3 py-2 font-semibold">Call #</th>
                              <th className="px-3 py-2 font-semibold text-right">Input Tokens</th>
                              <th className="px-3 py-2 font-semibold text-right">Output Tokens</th>
                              <th className="px-3 py-2 font-semibold text-right">Total Tokens</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-border">
                            {run.tokens.by_api_call.map((call, idx) => (
                              <tr key={idx} className="hover:bg-surface-3/30 transition-colors">
                                <td className="px-3 py-2 font-mono text-text-primary">#{call.call}</td>
                                <td className="px-3 py-2 font-mono text-text-secondary text-right">{call.input != null ? call.input.toLocaleString() : '-'}</td>
                                <td className="px-3 py-2 font-mono text-text-secondary text-right">{call.output != null ? call.output.toLocaleString() : '-'}</td>
                                <td className="px-3 py-2 font-mono text-text-primary font-semibold text-right">{call.total != null ? call.total.toLocaleString() : '-'}</td>
                              </tr>
                            ))}
                            {run.tokens.by_api_call.length > 1 && (
                              <tr className="bg-surface-3/20 font-bold border-t border-border">
                                <td className="px-3 py-2 text-text-primary">Total</td>
                                <td className="px-3 py-2 font-mono text-text-primary text-right">
                                  {run.tokens.input != null ? run.tokens.input.toLocaleString() : '-'}
                                </td>
                                <td className="px-3 py-2 font-mono text-text-primary text-right">
                                  {run.tokens.output != null ? run.tokens.output.toLocaleString() : '-'}
                                </td>
                                <td className="px-3 py-2 font-mono text-accent text-right">
                                  {run.tokens.total != null ? run.tokens.total.toLocaleString() : '-'}
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}
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
                    {(selectedSpan.attributes["argox.policy.rule_id"] || selectedSpan.attributes["rule_id"]) && (
                      <DetailBox 
                        label="Rule ID" 
                        value={(selectedSpan.attributes["argox.policy.rule_id"] || selectedSpan.attributes["rule_id"]) as string} 
                      />
                    )}
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

function CollapsibleBlock({ title, content, badge }: { title: string; content: string; badge?: string }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="border border-border rounded bg-surface-2/40 overflow-hidden mb-3">
      <div 
        className="flex items-center justify-between px-3 py-2 bg-surface-3/30 cursor-pointer hover:bg-surface-3/60 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-text-primary">{title}</span>
          {badge && (
            <span className="text-[10px] bg-accent-surface text-accent border border-accent-border px-1.5 py-0.5 rounded font-semibold tracking-wider uppercase">
              {badge}
            </span>
          )}
        </div>
        <Icon name={open ? "chevronUp" : "chevronDown"} size={14} className="text-text-muted" />
      </div>
      {open && (
        <div className="p-3 border-t border-border bg-bg-base/30">
          <pre className="text-xs font-mono text-text-secondary whitespace-pre-wrap break-words bg-bg-base p-2.5 rounded border border-border max-h-60 overflow-y-auto">
            {content || <span className="italic text-text-faint">Empty</span>}
          </pre>
        </div>
      )}
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
