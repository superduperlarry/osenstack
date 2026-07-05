# HANDOFF — Enstack Agent OS Session Log

**Session close: 04 Jul 2026 · Larry × Claude · Thread: Agent OS concept → customer deck → go-live architecture** Port this file into the next chat (execution phase). Canonical positioning still governed by ENOS\_PRE\_A\_Deck\_v12 / v10\_3 and the project source-of-truth list — this log covers the Agent OS workstream only.

---

## 1 · Deliverables produced (all in /outputs, uploaded by Larry to Drive)

| File | What it is | Status |
| :---- | :---- | :---- |
| `Enstack_Agent_OS_Wireframe.html` | Customer-facing product wireframe: 4 app screens (Home / Pay / Limits / Activity), API surface, architecture diagram. ENOS dark brand. | Final v2 (customer-facing language) |
| `Enstack_Agent_OS.pptx` | 12-slide customer deck. Real enos wordmark (lime on dark / evergreen on light). Email: [hello@enosone.com](mailto:hello@enosone.com). | Final, QA'd |
| `Enstack_Agent_OS_GoLive_Architecture.pptx` | 16-slide go-live architecture blueprint (internal). | Final, QA'd (programmatic QA — image preview glitched; eyeball pass recommended) |
| Vercel prototype | [https://enstack-agent-os-site.vercel.app/](https://enstack-agent-os-site.vercel.app/) — Larry's narrative site built from the wireframe. | Marketing-only going forward |

## 2 · Product definition (locked this session)

- **Name:** **Enstack Agent OS** (customer-facing). One-liner: *"Give your AI agents real money — and real control."*  
- **Three money primitives per agent:** Balance (stablecoin under the hood; never say so to customers) · Visa card (white-label) · virtual bank account (SGB).  
- **Three surfaces:** webapp · iOS/Android · API \+ MCP. Local last-mile rails (FPS/PIX/UPI/SEPA-Inst/ACH/e-wallets) \+ cross-border (SWIFT/SEPA/ACH) under OSN routing.  
- **Positioning inside ENOS:** Enstack owns the surface/distribution; **OSN owns rails/FX/routing (infrastructure side, per Larry's directive)**; partners power primitives. This is the agentic row above the a16z map made literal.  
- **Customer-facing language rules:** no "stablecoin/USDC/onchain/OSN" in customer materials → "Balance," "best way to pay," "Enstack Routing." Trust anchors forward: Central Bank of Bahrain (SGB), Visa, Standard Chartered, "you approve every rule."  
- **The moat \= the agent authorization layer** (owner→agent→credential model \+ policy engine: limits, HIL approvals, allowlists, audit). Providers are replaceable adapters.

## 3 · Architecture (locked this session — full detail in GoLive deck)

- **Not a new stack.** Agent OS productizes the canonical **Enos Hub** (ENOS Platform Architecture.pdf / Master Plan — canonical, override recollection): FastAPI `/v1` (OpenAPI 3.1, TS+Py SDKs), Aurora double-entry append-only ledger, Celery/RabbitMQ saga workflow engine, provider-abstraction registry, **MCP server already specified as the single agent contract**, AWS Singapore primary \+ Tokyo DR, Terraform-only.  
- **Mobile \= Capacitor** wrapping static-exported Next.js (canonical; NOT React Native).  
- **Hosting:** product app on canonical AWS (S3+CloudFront+WAF); **Vercel stays marketing-only**.  
- **Wallet layer — 3 modes, one interface:** A) partner-custodied (Phase 1 default; Fireblocks/Circle-class), B) embedded self-custody (Privy/Turnkey/Dfns; fits canonical *"transient hot wallets only — never custodial"* constraint), C) BYO (WalletConnect / ERC-4337 session keys; Phase 2).  
- **Agent identity model:** Owner (KYC/KYB) → Agents (sub-principals, no separate KYC; owner liability) → Credentials (scoped keys/MCP tokens) → Policy. Everything auditable to agent AND owner.  
- **Ecosystem strategy:** "choose your payment provider like your LLM." MCP native Phase 0; Hermes/OpenClaw/LangChain plugins Phase 1; x402 \+ AP2/ACP mandate mapping Phase 2\. Protocol-promiscuous at the edge, one policy engine at the core.  
- **Roadmap:** Phase 0 sandbox (wks 0–8) → Phase 1 invite-only pilot HK+PH (8–20) → Phase 2 GA \+ app stores (20–36). Exit criteria per phase in deck slide 14\.

## 4 · Provider intel gathered

- **SGB \= Singapore Gulf Bank** (sgb.com, fetched 24 Jun 2026): CBB **wholesale** licence, Mumtalakat \+ Whampoa backed, Standard Chartered cross-border clearing. Wholesale ⇒ model is **ENOS master account \+ virtual named accounts in the Enos ledger** — not retail IBANs per agent.  
- **Banki** (Investor Deck v8.1, 22 Jun 2026): white-label Visa via PFH Principal Member ($850M/mo), HK lender licence; $4/$40 cards, KYC $5, min 1,000, FX 1.8–2.8%, 50:50 profit share; 8 wks distribution / 12–18 wks co-brand.  
- **RedotPay CaaS** (project docs): $50k setup \+ $10k scheme, virtual $0/physical $20+$15, FX 1.2%, 1% holder fee w/ 50bps rebate, KYC $3/KYT $0.10, $5k/mo minimum, **float \= 5 days GDV**, 3-yr term, 180+ countries.

## 5 · OPEN DECISION GATES (⚑ all block Phase 1, none block Phase 0\)

1. **Card issuer** — Banki vs RedotPay: unit model with **Matthew** (GDV \+ float cost decide). Build adapter either way.  
2. **Wallet custody sequencing** — Mode A partner selection \+ Mode B legal posture per market → **Hayley** (HK VASP, PH BSP; MSO does NOT cover client crypto custody).  
3. **SGB agreement scope** — virtual-account issuance, naming, API vs file instruction, **public naming rights** (currently named in customer deck slide 8 — verify before external circulation).  
4. **Hosting cutover** — Vercel→AWS timing for product app.  
5. **Protocol posture** — MCP now; x402/AP2 committed to Phase 2 backlog.

Recommendation on record: run gates 1–4 in parallel over two weeks.

## 6 · Brand & production notes (for the build pipeline)

- Real **enos wordmark** processed from `wordmark_green.png`: alpha from red-channel contrast, two variants (evergreen `183A2D` light slides / lime `D8FF32` dark slides), aspect 3.549. Regenerate per session — container resets.  
- Fonts (Playfair Display, Space Grotesk, Noto Sans) fetched from Google Fonts GitHub raw → `~/.fonts` \+ `fc-cache`. Phone-screen renders: `wkhtmltoimage` with CSS `zoom` (not `--zoom` flag — distorts aspect).  
- Deck pipeline: pptxgenjs → `rezip.py` → LibreOffice PDF → `pdftoppm` QA. This session the view-tool image preview failed mid-stream; fallback QA \= python-pptx canvas-bounds \+ text-fit heuristic \+ pdftotext keyword check \+ pixel sampling. Worked; keep as fallback pattern.  
- Contact locked: [**hello@enosone.com**](mailto:hello@enosone.com).

## 7 · Next chat setup (execution phase)

Attach/reference: this handoff · `Enstack_Agent_OS_GoLive_Architecture.pptx` · **ENOS Platform Architecture.pdf** (canonical stack) · **ENOS Master Plan.pdf** · OSN On/Off-Ramp API Docs v4.0.3 (referenced in Master Plan) · Banki deck v8.1 · RedotPay pricing docs.

First execution deliverables (pick one per chat):

- OpenAPI 3.1 spec draft for `/v1` Agent OS surface \+ MCP tool catalog  
- Hayley custody memo (Mode A/B legal posture, HK \+ PH)  
- Matthew card unit model (Banki vs RedotPay, GDV scenarios)  
- Enterprise console \+ onboarding wireframes (extends approved wireframe)  
- Phase-0 repo scaffold (→ Claude Code territory, see below)

**Chat vs Claude Code:** strategy, specs, decks, memos, models → chat (this project). Repo scaffolding, FastAPI skeleton, MCP server code, Next.js app build → **Claude Code against the GitHub repo**, with this handoff dropped in-repo as `CLAUDE.md` context. Claude (chat) cannot push to GitHub or hand off to Claude Code directly — this file is the bridge.  
