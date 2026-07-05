# Enstack Agent OS — MCP Tool Catalog (v1.0.0-draft.1)

Companion to `agent_os_openapi.yaml`. The MCP server (`enos-mcp`, per Platform Architecture §6.6) is **the single agent contract**: every tool below is a thin, audited wrapper over a `/v1` REST operation. One policy engine, two doors.

**Rule zero:** the MCP surface never exposes a capability the REST surface doesn't have, and never bypasses Policy. Effective capability per call \= `credential scopes ∩ agent Policy`, evaluated server-side.

---

## 1 · Authentication & attribution

- MCP clients authenticate with an **agent credential of `kind: mcp`** (`ac_live_…` / `ac_test_…`), issued via `POST /v1/agents/{id}/credentials`.  
- One credential \= one agent. The server derives agent \+ owner identity from the token; there is no `agent_id` parameter on agent-scoped tools — an agent cannot name another agent.  
- Every tool invocation writes to `mcp_audit` (append-only): credential, agent, owner, tool, arguments hash, result status, request\_id. Non-negotiable.  
- Idempotency: mutating tools accept an optional `idempotency_key` argument; if the client omits it, the MCP server generates one per invocation and records it in the audit row. Retries by the client SHOULD reuse the key.

## 2 · Tool catalog (agent-scoped)

| Tool | Maps to | Required scope | Mutating | Notes |
| :---- | :---- | :---- | :---- | :---- |
| `get_balance` | `GET /agents/{id}/balance` | `balance:read` | no | Own balance only. |
| `get_funding_instructions` | `GET /agents/{id}/funding_instructions` | `balance:read` | no | How to top me up. |
| `get_policy` | `GET /agents/{id}/policy` | `policy:read` | no | Read-only; lets the agent plan within limits instead of discovering them by failing. |
| `create_quote` | `POST /quotes` | `quotes:create` | yes | Firm until `expires_at`. |
| `get_quote` | `GET /quotes/{id}` | `quotes:create` | no |  |
| `create_payment` | `POST /payments` | `payments:create` | yes | Three outcomes: `processing`, `pending_approval` (Approval raised, owner notified — **not an error**), or `policy_denied`. The tool result states which, so the agent can reason about next steps. |
| `get_payment` | `GET /payments/{id}` | `payments:read` | no | Includes status timeline. |
| `list_payments` | `GET /payments` | `payments:read` | no | Own payments only. |
| `cancel_payment` | `POST /payments/{id}/cancel` | `payments:create` | yes | Pre-dispatch only. |
| `create_transfer` | `POST /transfers` | `transfers:create` | yes | Internal balance moves; policy-evaluated. |
| `list_transfers` | `GET /transfers` | `transfers:read` | no |  |
| `create_counterparty` | `POST /counterparties` | `counterparties:create` | yes | Starts `unverified`; may itself raise an Approval under `require_approval_for_new_counterparties`. |
| `list_counterparties` | `GET /counterparties` | `counterparties:read` | no | Masked destination details. |
| `get_counterparty` | `GET /counterparties/{id}` | `counterparties:read` | no |  |
| `list_cards` | `GET /agents/{id}/cards` | `cards:read` | no | Masked; PAN/CVV never traverse MCP. |
| `freeze_card` | `POST /cards/{id}/freeze` | `cards:freeze` | yes | Agent may freeze its own card. **Unfreeze is owner-only** — deliberately absent from this catalog. |
| `list_approvals` | `GET /approvals` | `approvals:read` | no | Only approvals raised by this agent's own actions. Lets an agent check "is my payment still waiting on the owner?" |
| `get_approval` | `GET /approvals/{id}` | `approvals:read` | no |  |
| `list_activity` | `GET /activity` | `activity:read` | no | Own events only. |

## 3 · Deliberately excluded from the agent MCP surface

These exist in `/v1` under **owner scope only** and are never MCP tools:

- Agent lifecycle: create / suspend / reactivate agents  
- Credential issuance and revocation  
- Policy writes (`PUT /agents/{id}/policy`)  
- Approval decisions (`approve` / `reject`)  
- Counterparty verification  
- Card unfreeze  
- Webhook endpoint management

The asymmetry is the product: agents operate inside the box; only the owner reshapes the box. An agent can always *see* its constraints (`get_policy`) and *request* passage (any held action raises an Approval); it can never widen them.

## 4 · MCP resources & prompts

- **Resource `policy://current`** — the agent's active Policy document (mirrors `get_policy`; useful for clients that preload context).  
- **Resource `balance://current`** — current balance snapshot.  
- **Prompt `plan_payment`** — guided template: check policy → check balance → quote → create payment → handle `pending_approval`. Ships so third-party agent frameworks get the happy path for free.

## 5 · Webhook topic catalog (AsyncAPI stub — full spec is a Phase 0 sibling deliverable)

| Topic | Fired when |
| :---- | :---- |
| `payment.processing` / `payment.completed` / `payment.failed` / `payment.cancelled` / `payment.returned` | Payment lifecycle |
| `approval.requested` | A policy rule held an action — the primary owner-notification hook |
| `approval.decided` | Owner approved / rejected / approval expired |
| `transfer.completed` | Internal transfer settled |
| `balance.credited` | Inbound funds posted (virtual account or card refund) |
| `card.authorization.approved` / `card.authorization.declined` | Real-time card decisions, with policy rule on declines |
| `agent.suspended` / `agent.reactivated` | Agent lifecycle |
| `credential.revoked` | Credential killed |
| `policy.updated` | New policy version active |

Delivery: HMAC-SHA256 signed (`Enstack-Signature`), exponential-backoff retries, console replay — per canonical Webhooks machinery.

## 6 · Design decisions on record (this draft)

1. **Approvals are 202s, not errors.** An over-limit payment is a held object with an ID, not a rejection. This is what makes HIL legible to agent loops.  
2. **Policy is replaced whole (PUT), versioned, immutable.** No patch semantics — a policy diff must be reviewable as a single artifact.  
3. **No `amount`\-plus-`quote_id` ambiguity.** Cross-currency requires a quote; same-currency takes an amount. One or the other, validated server-side.  
4. **Attribution is structural.** `credential_id` on every Payment, both `agent_id` and `credential_id` on every ActivityEvent. Matches the canonical audit posture (Platform Architecture §10).  
5. **Money \= decimal strings everywhere.** Matches `decimal.Decimal` / `numeric` canonical rule. Any SDK that emits floats fails review.  
6. **Customer-safe vocabulary.** "Balance," "Enstack Routing," rail names — nothing else, per the locked language rules. The spec is publishable as-is.

## 7 · ⚑ Open items carried into build (flags, not blockers for Phase 0 sandbox)

1. **Virtual-account naming scheme** — spec assumes `{owner_legal_name} — {agent_display_name}`; final format gated on the banking-partner agreement scope (open gate 3, per handoff). Field shapes won't change; the naming description might.  
2. **Card issuer choice** (open gate 1\) — `Card` schema is issuer-agnostic by design; `network` enum currently `visa` only. Revisit if the unit model lands elsewhere.  
3. **PCI reveal flow** — card detail reveal deliberately out of `/v1` scope; needs a decision between issuer-hosted reveal widget vs. our PCI-scoped token endpoint. Phase 1\.  
4. **x402 / AP2 mandate mapping** — Phase 2 backlog per protocol posture; the `Approval` object is the natural mandate anchor when it lands.  
5. **Rate limits** — envelope supports `rate_limited`; numeric tiers TBD with infra sizing.

---

*Draft for internal review · 04 Jul 2026 · Pair with `agent_os_openapi.yaml` and `HANDOFF_Enstack_Agent_OS_Session.md` as `CLAUDE.md` context in the repo.*  
