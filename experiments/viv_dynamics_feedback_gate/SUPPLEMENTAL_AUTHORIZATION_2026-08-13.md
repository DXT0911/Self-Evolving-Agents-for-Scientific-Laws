# Supplemental authorization, 2026-08-13

The user explicitly authorized an additional 12,000 requested evaluations to replace the
interrupted direct-PySR arm. The interrupted reservation remains consumed. The replacement
three-arm run retains its 36,000 ceiling, so the cumulative hard ceiling is 48,000 requested
evaluations.

The DeepSeek ceiling remains 1,200,000 tokens across both Hamilton arms. Private/OOD access
remains forbidden. The replacement must use a new launch directory and cannot reuse or alter
the failed attempt's ledger, checkpoint, logs, or partial outputs.

## Final Promotion retry authorization

After the first fit-only Round 3 Promotion request hung with no response, the user authorized
exactly one retry of that Promotion. The fit-only Hamilton ceiling is increased from 600,000
to 669,347 tokens, and the aggregate ceiling for both Hamilton arms is increased from
1,200,000 to 1,269,347 tokens. The retry may consume at most 69,347 additional tokens.

This authorization adds no requested evaluations. It does not authorize another PySR search,
another Promotion retry, private/OOD access, or execution of either downstream arm before the
fit-only endpoint gate has closed normally.
