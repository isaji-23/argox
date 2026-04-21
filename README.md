# Argox

**Open-source observability, governance and auditing for AI Agents.**

Argox is an SDK that gives engineering teams full visibility into what their AI agents are doing, why they're doing it, and whether they should be allowed to. It captures every decision, tool call and output in real time, evaluates them against configurable policies, and stores everything in an auditable trail designed for regulatory compliance.

---

## Why this exists

AI agents are moving from demos to production. Once they run autonomously (calling tools, spending money, making decisions) you need answers to questions that logging alone can't solve:

- **What did the agent actually do?** Full traces of every step, not just the final output.
- **Was it allowed to do that?** Real-time policy evaluation that can log, alert or block actions before they happen.
- **How much did it cost?** Cost tracking so nothing runs away silently.

Existing tools either focus on prompt engineering, lock you into a SaaS platform, or treat governance as an afterthought. Argox treats it as the core problem.

## What it does

### Automatic instrumentation

Drop the SDK into your agent code and it captures inputs, outputs, decisions and errors with minimal overhead using decorators. 

### Policy engine

Define rules (cost limits, prohibited actions, compliance requirements) and the engine evaluates them in real time against every agent action. Policies are distributed to all connected agents.

### Auditable storage

Every trace, policy decision and configuration change is persisted with full metadata and timestamps.

### Dashboard

A web interface for exploring agent timelines, monitoring costs, reviewing policy events and verifying audit integrity.

## Design principles

**Low overhead.** The SDK lives in your agent's process and is engineered to add minimal latency. Policy evaluation happens against a local cache, no network round-trips in the hot path.

**Fail-open by default.** If the monitoring infrastructure degrades, your agents keep running. Strict enforcement is opt-in and explicit, never a surprise.

**Self-hosted first.** The entire stack runs on your infrastructure. No data leaves your environment unless you explicitly configure it to. No SaaS dependency, no phone-home, no telemetry by default.

**Data sovereignty by design.** Sensitive data can be redacted at the edge before it ever leaves the agent process. Audit logs are append-only with cryptographic integrity. This isn't a feature, it's an architectural constraint.

## EU AI Act compliance

Argox is built with the EU AI Act (Regulation 2024/1689) in mind. The SDK provides tooling that helps deployers and operators meet key obligations around risk management, record-keeping, transparency and human oversight. Pre-built policy templates cover common compliance scenarios out of the box.

> [!NOTE]
> Argox is a technical tool, not legal advice. It provides the infrastructure for compliance but does not guarantee it. Consult qualified legal counsel for your specific obligations.

## Project status

🚧 **Active development - not yet production-ready.**

We're building in the open. The architecture is defined, core components are under development, and we welcome early feedback.

## Contributing

Argox is open source and we actively welcome contributions. Whether it's bug reports, feature suggestions, documentation improvements or code.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a pull request.

## Team

| Name | Role | GitHub |
|------|------|--------|
| Iñigo S. Jiménez Montoro | Developer | [@isaji-23](https://github.com/isaji-23) |
| Marcos Calvo Sánchez | Developer | [@MarcosCS2004](https://github.com/MarcosCS2004) |
| Ángel Toledo Rodelgo | Developer | [@Negerty48](https://github.com/Negerty48) |
| Daniel Andrés Castillo Olivares | Technical Advisor | [@DanielAndresCastillo](https://github.com/DanielAndresCastillo) |
| Jose Vicente Sáez Ibáñez | Technical Advisor | [@jovisaib](https://github.com/jovisaib) |

## License

This project is licensed under the [Apache License 2.0](LICENSE), you're free to use, modify and distribute it, including in commercial products.

## Acknowledgments

Argox is a Final Master's Thesis (TFM) project developed as part of the Master's in Artificial Intelligence and Big Data at **Tajamar Tech** with the support of **Microsoft**.

Built in collaboration with **Aliando**, the project bridges academic research and real-world engineering needs, applying what we've learned about AI systems, data pipelines and large-scale architectures to a problem that the industry is actively trying to solve: how to monitor, govern and audit autonomous AI agents in production.

---

<p align="center">
  <sub>If Argox is useful to you, a ⭐ on the repo helps others find it.</sub>
</p>