# Public VIV dynamics-gate research: paused state

Status: safely paused after fit-only numeric search; Round 3 Promotion closure remains pending.

## Completed work

- The public fit-only Hamilton arm completed three governed PySR searches.
- Its evaluation ledger contains exactly three completed reservations totaling 12,000 requested
  evaluations.
- The Round 3 frozen result remains completed and unchanged. Its selected equation is
  `a = 1.69537218076573 - 161.028555267758*x`, with validation R²
  `0.5277851045730679` and scientific score `0.6920176495663919`.
- Recovery defects found during Promotion were fixed in the controller, editor, token preflight,
  and DeepSeek reasoning configuration. The focused Hamilton suite passes 91 tests.

## Incomplete work

Round 3 Promotion is pending after attempt 5. No numeric search needs to be repeated, but these
four deterministic audit findings still require correction before the fit-only endpoint can be
frozen:

1. retain `history/round2/results/result.json` as the incumbent;
2. enumerate exactly all three completed valid-round results and exclude invalid attempts from
   scientific evidence;
3. record residual feedback for Round 3;
4. cite `history/round3/results/result.json` in that residual feedback.

Promotion attempt 5 demonstrated that provider-side thinking must be disabled for this bounded
tool-execution recovery. It consumed 86,377 of its authorized 90,000 tokens and stopped at the
hard token preflight without exceeding the attempt ceiling. It made no scientific-document
edits and did not call `finish`.

## Frozen resource state

- Cumulative requested evaluations consumed or reserved: 24,000 / 48,000.
  - interrupted direct PySR: 12,000;
  - replacement fit-only Hamilton: 12,000;
  - dynamics-aware Hamilton: 0;
  - replacement direct PySR: 0.
- Fit-only tokens recorded or conservatively charged: 853,859 / 857,482.
- Aggregate Hamilton ceiling: 1,457,482.
- Private/OOD access remains forbidden and unused.

## Downstream gate

The following actions are not authorized while paused:

- another Promotion attempt;
- fit-only endpoint evaluation or freeze;
- dynamics-aware Hamilton;
- replacement direct PySR;
- private/OOD evaluation.

## Resume contract

Resume from Promotion attempt 6; do not rerun PySR rounds 1–3. Before execution, create a new
explicit authorization and lock. The recommended bounded recovery disables DeepSeek provider
thinking, limits each completion to 6,000 tokens, permits at most 30,000 additional tokens, and
adds zero requested evaluations. Run the existing four-error scientific correction and require
the deterministic closure audit to pass before opening any downstream gate.
