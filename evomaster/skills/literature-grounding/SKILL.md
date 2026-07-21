---
name: literature-grounding
description: Build cited, broad physical priors before blind symbolic-regression discovery. Use at the start of a Hamilton benchmark when the agent may search scholarly metadata but must not see or reconstruct the benchmark equation, coefficients, term list, or private evaluation labels.
---

# Literature Grounding

Ground the first discovery round in public scientific knowledge without converting the
literature into an answer template.

## Workflow

1. Read the public task only. Do not search for the benchmark name, baseline method,
   reference equation, dataset publication, or known answer.
2. Form 2-4 broad mechanism queries from the phenomenon and task goal. Cover distinct
   themes such as restoring behavior, energy balance, oscillatory stability, dimensional
   consistency, or parameter-dependent shared structure.
3. Call `literature_search` for each query. Prefer a mix of foundational and recent
   sources. Do not claim to have read full text when only metadata or an abstract is
   available.
4. Keep only statements supported by at least one returned source. Cite title, year, and
   DOI URL. Mark conflicts and uncertainty.
5. Write the machine-readable `EVO_INITIAL_PRIORS` block in `plan.md` before creating the
   first symbolic-regression configuration.

## Integrity boundary

Allowed outputs:

- qualitative mechanisms;
- invariances, symmetries, conservation or energy-balance considerations;
- dimensional requirements;
- qualitative stability behavior;
- a hypothesis that multiple operating conditions may share structure;
- uncertainty and possible regime boundaries.

Forbidden outputs:

- a candidate differential equation;
- a list of monomials or exact nonlinear terms;
- coefficient values, signs tied to specific candidate terms, or polynomial orders;
- a PySR template derived from a paper;
- the private benchmark method, answer, labels, or test metrics.

Do not turn a broad fact such as “nonlinear energy exchange may saturate oscillations”
into a prescribed algebraic form. Let symbolic regression discover that form.

## Required plan block

```text
<!-- EVO_INITIAL_PRIORS_BEGIN -->
{
  "status": "completed",
  "queries": ["broad query 1", "broad query 2"],
  "sources": [
    {
      "id": "S1",
      "title": "paper title",
      "year": 2024,
      "url": "https://doi.org/..."
    }
  ],
  "priors": [
    {
      "statement": "qualitative, non-template physical fact",
      "evidence_sources": ["S1"],
      "scope": "where this fact may apply",
      "strength": "hypothesis"
    }
  ],
  "candidate_template_proposed": false
}
<!-- EVO_INITIAL_PRIORS_END -->
```

Use at least two sources and three priors. Allowed strengths are `hypothesis` and
`supported`; abstract-only evidence normally supports no stronger than `hypothesis`.
