# Design intent: okf-artifact-knowledge-freshness-semantics

## Idea

okf read-plane serves freshness but no artifact knowledge. Two gaps from live mesh testing: (1) artifact metadata/content — query_knowledge returns only ref/served_commit/freshness; an okf://ralph/ralph-lifecycle-doc@fresh ref tells the consumer nothing about what the artifact IS (type, path, size, content summary), so consumer intents like 'review the doc' stay formal; (2) freshness semantics — observed null freshness with a moved served_commit, and null→fresh transition timing is opaque; nobody can explain when the gate unblocks, making blocked_upstream states hard to diagnose.

## Primary design home

okf-mcp-server

## Affected projects

- **okf-mcp-server** — executor, okf-plane
- **control-gateway** — mesh-control, executor

## Handoff sketch

Materialize as an RFC/design doc in okf-mcp-server backlog/. Split: (1) artifact metadata surface — type/path/summary for each okf:// ref, served alongside commit/freshness in the existing status surface so gateway's query_knowledge can pass it through without a new contract; (2) freshness semantics doc + observability — when null→fresh transitions happen, what recalculates them, so goal blocked_upstream diagnostics are explainable. Gateway side is consumer-only: pass metadata through query_knowledge (covered by the sibling design-intent spooled in control-gateway).

## okf relevance

This IS the okf-plane gap: okf:// refs currently expose only owner/ref/served_commit/freshness. Consumers (e.g. offdesk review gates) reference okf://owner/artifact@fresh without knowing what the artifact is — file? dir? commit? Adding artifact metadata makes consumer intents concrete and lets planning clients verify that a producer's artifact actually matches what downstream members expect.
