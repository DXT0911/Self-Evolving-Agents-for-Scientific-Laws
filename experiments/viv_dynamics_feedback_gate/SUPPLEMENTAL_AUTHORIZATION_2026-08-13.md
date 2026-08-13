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

## Second final Promotion retry authorization

After Promotion attempt 2 was terminated by the host command's execution timeout, the user
explicitly authorized exactly one further retry, limited to fit-only Round 3 Promotion. The
fit-only Hamilton ceiling is increased from 669,347 to 738,694 tokens, and the aggregate
ceiling for both Hamilton arms is increased from 1,269,347 to 1,338,694 tokens. This retry may
consume at most 69,347 additional tokens.

This authorization adds no requested evaluations and leaves their cumulative ceiling at
48,000. It does not authorize another PySR search, a retry beyond Promotion attempt 3,
private/OOD access, or either downstream arm before normal fit-only endpoint closure.

## Promotion attempt 4 audit-correction authorization

After attempt 3 returned normally but failed four deterministic scientific-audit checks, the
user explicitly authorized Promotion attempt 4 solely to correct those four reported errors.
Attempt 3 used 8,066 tokens, leaving 61,281 tokens within the already authorized fit-only
ceiling of 738,694. The aggregate Hamilton ceiling remains 1,338,694 tokens.

Attempt 4 may use at most those remaining 61,281 tokens. It adds no requested evaluations and
does not authorize PySR search, private/OOD access, unrelated scientific changes, a fifth
Promotion attempt, or either downstream arm before normal fit-only endpoint closure.
