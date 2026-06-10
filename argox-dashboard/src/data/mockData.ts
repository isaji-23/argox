/* ============================================================
   ARGOX — SAMPLE DATA (believable, internally consistent)
   ============================================================ */

// Tiny seeded RNG for deterministic "random" series
function mulberry32(a: number) {
  return function() {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

export const MODELS = [
  { id: 'gpt-4o',            label: 'gpt-4o',            color: 'var(--span-llm)' },
  { id: 'claude-3.7-sonnet', label: 'claude-3.7-sonnet', color: 'var(--span-tool)' },
  { id: 'gpt-4o-mini',       label: 'gpt-4o-mini',       color: 'var(--span-processor)' },
  { id: 'llama-3.3-70b',     label: 'llama-3.3-70b',     color: 'var(--gold)' },
];

export const AGENTS = [
  'billing-copilot', 'support-triage', 'data-extractor',
  'code-reviewer', 'sales-research', 'doc-summarizer', 'invoice-auditor',
];

export const ENVS = ['production', 'staging', 'dev'];

export const TIME_RANGES = [
  { value: '1h',  label: 'Last 1 hour' },
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d',  label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
];

// ---- Featured trace: a blocked refund workflow (the differentiator) ----
export const FEATURED_TRACE = {
  id: 'b7f3a9c1e204d8f6',
  name: 'refund_workflow.execute',
  agent: 'billing-copilot',
  env: 'production',
  model: 'gpt-4o',
  startedAt: '2026-06-08T14:21:07.412Z',
  startedHuman: 'Jun 8, 14:21:07',
  durationMs: 4820,
  status: 'error',          // ended in a policy block
  decision: 'block',
  spanCount: 14,
  tokensIn: 8420,
  tokensOut: 1163,
  costUsd: 0.1184,
  service: 'billing-svc',
  sdk: 'argox-py 0.9.2',
};

// Waterfall spans for the featured trace. t = ms offset from trace start.
export const FEATURED_SPANS = [
  { id:'s0',  parent:null, name:'refund_workflow.execute', type:'root',      t:0,    d:4820, decision:'block', status:'error' },
  { id:'s1',  parent:'s0', name:'load_account_context',    type:'processor', t:14,   d:210,  decision:'allow', status:'ok' },
  { id:'s2',  parent:'s1', name:'vector_search · kb',      type:'tool',      t:42,   d:148,  decision:'allow', status:'ok', tool:'vector_search' },
  { id:'s3',  parent:'s0', name:'llm · classify_intent',   type:'llm',       t:240,  d:712,  decision:'allow', status:'ok', model:'gpt-4o' },
  { id:'s4',  parent:'s0', name:'sql_query · orders',      type:'tool',      t:980,  d:386,  decision:'allow', status:'ok', tool:'sql_query' },
  { id:'s5',  parent:'s0', name:'llm · reason_eligibility',type:'llm',       t:1400, d:1180, decision:'warn',  status:'ok', model:'gpt-4o', rule:'pii.egress.scan' },
  { id:'s6',  parent:'s5', name:'redact_pii',              type:'processor', t:1520, d:96,   decision:'allow', status:'ok' },
  { id:'s7',  parent:'s0', name:'http_request · stripe',   type:'tool',      t:2620, d:540,  decision:'allow', status:'ok', tool:'http_request' },
  { id:'s8',  parent:'s0', name:'llm · draft_resolution',  type:'llm',       t:3210, d:690,  decision:'allow', status:'ok', model:'gpt-4o' },
  { id:'s9',  parent:'s8', name:'format_output',           type:'processor', t:3760, d:72,   decision:'allow', status:'ok' },
  { id:'s10', parent:'s0', name:'refund_issue · execute',  type:'tool',      t:3980, d:118,  decision:'block', status:'error', tool:'refund_issue', rule:'finance.refund.max_amount' },
  { id:'s11', parent:'s0', name:'send_email · customer',   type:'tool',      t:4140, d:8,    decision:'block', status:'error', tool:'send_email', rule:'comms.external.requires_approval' },
  { id:'s12', parent:'s0', name:'emit_audit_evidence',     type:'processor', t:4180, d:610,  decision:'allow', status:'ok' },
];

export const FEATURED_RUN = {
  prompt: `Customer refund request — ticket #48211.

Customer: [REDACTED:name] (acct [REDACTED:acct_id], tier: business)
Order: ORD-9F23-118  ·  $1,840.00  ·  placed 2026-05-29
Reason given: "Service was down for 4 days during launch, want a full refund."

Issue an appropriate refund per policy, notify the customer, and log the decision.`,
  output: `Eligibility assessed: partial refund recommended ($552.00, 30% SLA credit per business-tier SLA §4.2).

⛔ Action halted by policy before execution:
 • refund_issue blocked — requested $1,840.00 exceeds finance.refund.max_amount ($500.00 without approval).
 • send_email blocked — external comms require human approval (comms.external.requires_approval).

No refund was issued and no email was sent. Escalation ticket ESC-3320 created for a human reviewer.`,
  toolCalls: [
    { name:'vector_search',  durationMs:148, blocked:false, result:'4 KB articles matched · "refund eligibility business tier"' },
    { name:'sql_query',      durationMs:386, blocked:false, result:'1 row · order ORD-9F23-118 · status=fulfilled · amount=1840.00' },
    { name:'http_request',   durationMs:540, blocked:false, result:'200 OK · stripe.charges.retrieve · ch_3Pqr…892 · refundable=true' },
    { name:'refund_issue',   durationMs:118, blocked:true,  rule:'finance.refund.max_amount',         result:'DENIED · amount 1840.00 > limit 500.00 (no approval token present)' },
    { name:'send_email',     durationMs:8,   blocked:true,  rule:'comms.external.requires_approval',  result:'DENIED · external recipient requires approval gate' },
  ],
  llmCalls: [
    { n:1, label:'classify_intent',     model:'gpt-4o', tokensIn:1240, tokensOut:86  },
    { n:2, label:'reason_eligibility',  model:'gpt-4o', tokensIn:4980, tokensOut:612 },
    { n:3, label:'draft_resolution',    model:'gpt-4o', tokensIn:2200, tokensOut:465 },
  ],
  violations: [
    {
      rule:'finance.refund.max_amount', severity:'block', span:'s10', tool:'refund_issue',
      message:'Refund amount $1,840.00 exceeds the unattended ceiling of $500.00. Refunds above the ceiling require an approval token from a finance reviewer.',
      remediation:'Attach approval token `fin.approve:<reviewer>` or split into an approved manual refund.',
    },
    {
      rule:'comms.external.requires_approval', severity:'block', span:'s11', tool:'send_email',
      message:'Outbound email to an external recipient was attempted without an approval gate. External communication from billing-copilot is gated in production.',
      remediation:'Route through `comms.queue.review` or enable auto-approval for templated SLA notices.',
    },
    {
      rule:'pii.egress.scan', severity:'warn', span:'s5', tool:null,
      message:'Model input contained 2 entities matching PII patterns (name, acct_id). Entities were redacted upstream before egress; no action required.',
      remediation:'Informational — redaction succeeded.',
    },
  ],
};

// ---- Traces list ----
export function buildTraces() {
  const rng = mulberry32(42);
  const names = [
    'refund_workflow.execute','triage_ticket.run','extract_invoice.batch','review_pr.analyze',
    'enrich_lead.lookup','summarize_doc.chunk','reconcile_ledger.run','answer_query.rag',
    'classify_email.route','generate_report.compose','validate_contract.scan','plan_itinerary.build',
  ];
  const out = [FEATURED_TRACE];
  for (let i=0; i<27; i++) {
    const agent = AGENTS[Math.floor(rng()*AGENTS.length)];
    const model = MODELS[Math.floor(rng()*MODELS.length)].id;
    const r = rng();
    let decision = 'allow', status = 'ok';
    if (r > 0.86) { decision='block'; status='error'; }
    else if (r > 0.72) { decision='warn'; }
    if (rng() > 0.93 && decision==='allow') { status='error'; }
    const dur = Math.round(380 + rng()*6200);
    const mins = Math.floor(rng()*54);
    const out_i = {
      id: Array.from({length:16},()=>'0123456789abcdef'[Math.floor(rng()*16)]).join(''),
      name: names[Math.floor(rng()*names.length)],
      agent, env: rng()>0.25?'production':(rng()>0.5?'staging':'dev'),
      model,
      startedAt: new Date().toISOString(),
      startedHuman: `Jun 8, ${String(14-Math.floor(mins/12)).padStart(2,'0')}:${String(59-mins).padStart(2,'0')}:${String(Math.floor(rng()*59)).padStart(2,'0')}`,
      durationMs: dur,
      status, decision,
      spanCount: 3 + Math.floor(rng()*22),
      tokensIn: Math.floor(rng()*10000),
      tokensOut: Math.floor(rng()*2000),
      costUsd: +(0.004 + rng()*0.22).toFixed(4),
      service: 'agent-service',
      sdk: 'argox-py 0.9.2',
    };
    out.push(out_i);
  }
  return out;
}

// ---- Metrics series ----
export function buildMetrics(rangeKey: string) {
  const buckets = (rangeKey==='1h'?24 : rangeKey==='24h'?24 : rangeKey==='7d'?28 : rangeKey==='30d'?30 : 24);
  const rng = mulberry32(rangeKey==='7d'?7:rangeKey==='30d'?30:rangeKey==='1h'?1:24);
  const labelFor = (i: number) => {
    if (rangeKey==='7d') return ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][i%7];
    if (rangeKey==='30d') return `${i+1}`;
    if (rangeKey==='1h') return `${String((i*2.5|0)).padStart(2,'0')}m`;
    return `${String(i).padStart(2,'0')}:00`;
  };
  // cost stacked by model over time
  const cost = Array.from({length:buckets},(_,i)=>{
    const base = 0.6 + 0.4*Math.sin(i/3) + rng()*0.5;
    return {
      label: labelFor(i),
      'gpt-4o': +(base*1.6 + rng()*0.6).toFixed(2),
      'claude-3.7-sonnet': +(base*1.1 + rng()*0.5).toFixed(2),
      'gpt-4o-mini': +(base*0.4 + rng()*0.2).toFixed(2),
      'llama-3.3-70b': +(base*0.25 + rng()*0.15).toFixed(2),
    };
  });
  // latency histogram (ms buckets)
  const latBuckets = ['0-50','50-100','100-250','250-500','0.5-1s','1-2s','2-4s','4-8s','8s+'];
  const latShape = [3,8,19,27,21,12,6,3,1.2];
  const latency = latBuckets.map((b,i)=>({ label:b, count: Math.round(latShape[i]*120*(0.85+rng()*0.3)) }));
  
  // success ratio over time
  const success = Array.from({length:buckets},(_,i)=>{
    const fail = Math.max(0, 2 + 5*Math.abs(Math.sin(i/4)) + rng()*4);
    const blocked = Math.max(0, 1 + 3*Math.abs(Math.cos(i/3)) + rng()*2.5);
    return { label:labelFor(i), success:+(100-fail-blocked).toFixed(1), error:+fail.toFixed(1), blocked:+blocked.toFixed(1) };
  });
  // top agents by spend
  const topAgents = AGENTS.map((a)=>({ agent:a, spend:+(4+rng()*46).toFixed(2) }))
    .sort((x,y)=>y.spend-x.spend).slice(0,6);
  // top blocked tools
  const blockedTools = [
    { tool:'send_email',    count: 184 + (rng()*40|0) },
    { tool:'refund_issue',  count: 142 + (rng()*30|0) },
    { tool:'exec_python',   count: 96  + (rng()*30|0) },
    { tool:'file_write',    count: 61  + (rng()*20|0) },
    { tool:'http_request',  count: 38  + (rng()*16|0) },
    { tool:'sql_query',     count: 22  + (rng()*12|0) },
  ].sort((a,b)=>b.count-a.count);

  const totalCost = cost.reduce((s,r)=>s+(r['gpt-4o']||0)+(r['claude-3.7-sonnet']||0)+(r['gpt-4o-mini']||0)+(r['llama-3.3-70b']||0),0);
  const totalReq = success.length*1240;
  const avgSuccess = success.reduce((s,r)=>s+r.success,0)/success.length;
  const totalBlocked = blockedTools.reduce((s,t)=>s+t.count,0);

  return { cost, latency, latBuckets, p50:3, p95:6, p99:7.4, success, topAgents, blockedTools,
    kpis: {
      totalCost: +totalCost.toFixed(2),
      requests: totalReq,
      successRate: +avgSuccess.toFixed(1),
      blocked: totalBlocked,
      p95Latency: '1.9s',
    } };
}

export const POLICY_V7 = `# argox policy · billing-copilot
# version 7 · author: priya.n · 2026-06-08
apiVersion: argox.dev/v1
kind: PolicyBundle
metadata:
  agent: billing-copilot
  env: production

defaults:
  decision: allow
  audit: true                 # emit OTel evidence span

rules:
  - id: finance.refund.max_amount
    when:
      tool: refund_issue
      arg.amount: { gt: 500.00 }
    decision: block
    unless:
      approval_token: { present: true }
    reason: >
      Refunds over $500 require a finance approval token.

  - id: comms.external.requires_approval
    when:
      tool: send_email
      arg.recipient: { domain_not_in: [internal] }
    decision: block
    reason: External email needs human approval in prod.

  - id: pii.egress.scan
    when:
      span.kind: llm
    decision: warn
    detect:
      pii: [name, acct_id, email, card]
    action: redact            # redact before egress

  - id: tool.allowlist
    when:
      tool: { not_in: [vector_search, sql_query, http_request,
                       refund_issue, send_email] }
    decision: block
    reason: Tool not on the billing-copilot allowlist.
`;

export const POLICY_VERSIONS = [
  { v:7, author:'priya.n',  ts:'2026-06-08 14:02', note:'Lower refund ceiling 1000→500, block; gate external email', current:true,  yaml:POLICY_V7 },
  { v:6, author:'priya.n',  ts:'2026-06-01 09:18', note:'Add card to PII detectors', current:false, yaml:POLICY_V7 },
  { v:5, author:'marc.d',   ts:'2026-05-22 16:40', note:'Initial production bundle', current:false, yaml:POLICY_V7 },
];
