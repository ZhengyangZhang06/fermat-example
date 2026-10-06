# Upstream source notices

The accompanying notices are copied from
[`anthropics/fermats-last-theorem` at `6e837e75355538c7f80bab5b956861e86c4eacc2`](https://github.com/anthropics/fermats-last-theorem/tree/6e837e75355538c7f80bab5b956861e86c4eacc2).
They describe that upstream repository's complete contents, not a claim that all
of its files or web libraries are distributed here.

The experiment copies the 46-module Deuring proof closure from that revision,
including `Definitions/Def_WeierstrassCurve_RationalEnd.lean`, unchanged at their
original module paths. `import-manifest.json` records every Git blob and SHA-256;
its original reference status is retained as provenance, not a candidate verdict.
The new root proof in `Submission.lean` applies the upstream solution under the
experiment's exact frozen declaration. See
[`root-height-proof.md`](../../proofs/deuring-criterion/root-height-proof.md)
for the actual height/factorization argument and its validation boundary.

`reference-verification.json` records an earlier diagnostic only. Candidate
verification and independent review are separate gates; publication and theorem
acceptance remain the outer controller's responsibility. The original geometric
G/D/K outline remains historical evidence and is not the implemented route.
