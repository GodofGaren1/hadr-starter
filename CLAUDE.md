# CLAUDE.md

<!-- Fill in at least three conventions below before your first prompt.
     An empty conventions file is also a decision — just not one you made. -->

## Language & tooling

Python 3.9, standard library only (no pip dependencies). The pipeline must
run identically on the local machine and a bare GitHub Actions runner.

## Test command

```
python -m unittest discover -s tests -v
```

Tests are offline — no network, no fixtures on disk; events are constructed
in code and handed straight to reconcile/correlate/triage.

## Conventions

## Deviations policy
