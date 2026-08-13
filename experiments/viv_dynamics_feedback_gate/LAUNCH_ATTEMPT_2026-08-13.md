# VIV dynamics-feedback launch attempt, 2026-08-13

Status: invalid operational attempt; replacement direct-PySR budget not authorized.

The first background launch exited after a successful zero-budget preflight because its
PowerShell wrapper mixed log records with the integer exit code. The corrected wrapper then
started, but both Hamilton arms failed before Agent creation because prompt paths were resolved
relative to the generated bundle. They consumed zero LLM tokens and zero requested evaluations.

The wrapper incorrectly continued after those failures. Direct PySR reserved 12,000 requested
evaluations at `2026-08-13T02:16:26Z` before the process tree was stopped. It produced an early
checkpoint and hall-of-fame file but no completed `result.json`. Under the frozen protocol this
interrupted reservation remains consumed and cannot be erased or relabeled.

The attempt cannot support an arm comparison. A clean replacement needs the original remaining
24,000 evaluations for the two Hamilton arms plus an additional 12,000 for direct PySR, bringing
the cumulative ceiling including this failed attempt to 48,000. The DeepSeek ceiling remains
1,200,000 tokens because neither Hamilton arm reached an LLM call.

Corrective actions:

- generated Hamilton configs use absolute repository prompt paths;
- every execution or endpoint step now exits immediately on nonzero status;
- the failed ledger and checkpoint remain preserved in the ignored launch bundle;
- a new bundle must be generated in a separate directory after supplemental authorization.
