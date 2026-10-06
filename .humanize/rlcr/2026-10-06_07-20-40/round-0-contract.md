# Round 0 Contract

## Mainline objective
Resolve the inherited-root preservation review defect and deliver the exact selected child theorem as a clean committed, comparator-passing candidate.

## Target ACs
AC1 (exact theorem and baseline/source preservation) and AC2 (clean committed candidate passing the exact node comparator).

## Blocking side issues in scope
Canonical dependency readiness must precede any build. Audit whether the reported deletion still exists; restore only if needed. The inherited root warning must not be treated as a new child warning.

## Queued side issues out of scope
Solving the inherited root theorem, new decomposition or helper nodes, source refactoring, independent reviewer rerun, wiki publication, DAG transitions, and unavailable Task-system integration.

## Round success criteria
The baseline root block is byte-for-byte preserved; the child frozen type and proof are safe; DeuringCriterionStatement.lean and imports are unchanged. A clean committed SHA passes only the configured selected-node comparator with exit zero and `Your solution is okay!`. Record local-project provenance and verification evidence, then return to the controller.
