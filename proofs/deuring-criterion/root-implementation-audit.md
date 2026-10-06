# Root implementation audit

## Scope and provenance

The selected node is the exact frozen declaration in Submission.lean. Its new proof is an explicit application of the pinned upstream solution. There are no new named helper theorems. All 46 reference modules have been compared byte for byte via their SHA-256 manifest, including the already-present rationality definition (45 new source files). The existing three child proofs are unchanged and are not used by this route. DeuringCriterionStatement.lean, the verifier, the toolchain, dependency manifest, and frozen controller artifacts are unchanged.

## Independent prose and simplification review

The independent `review_root` agent inspected the actual root source and the numbered proof in root-height-proof.md. It found no mathematical defect. It checked the Frobenius twist and finite exceptional fibers in height composition; every factorization hypothesis; the Bezout construction of rational eta with alpha = p eta; the final scalar coefficients c = p²t′ − tp and e = p(p²n′ − q); and the height split a+b=c₀+pi. It confirmed that c≠0 uses integer cancellation, never cancellation on torsion points. The explicit qualified wrapper was judged already minimal and retained for provenance.

This is independent prose/simplification review, not the outer controller's final comparator review or theorem acceptance.

## Source audit

All copied source bytes were checked against import-manifest.json, and the full closure was scanned for placeholders, new axioms, unsafe declarations, native decision proofs, extern/implemented_by hooks, and kernel-skip patterns. No such proof constructs were found. P2M/Util.lean was inspected separately: its elaborators build ordinary proof terms and manage aliases/scopes; they do not bypass kernel validation. The upstream instance/simp attribute changes and preexisting linter settings are retained unchanged. Submission's frozen binders and conclusion and all inherited child text were compared against the parent revision.

## Warning-fatal build configuration

Run `lake build Submission` with the pinned Lean 4.33.1 toolchain. The package sets warningAsError=true. To keep upstream sources byte-identical, only P2M's preexisting deprecation/style diagnostics are filtered by library-scoped options: linter.deprecated, linter.style.haveILetI, linter.unusedSimpArgs, linter.unusedSectionVars, linter.unreachableTactic, linter.unusedVariables, and linter.unusedTactic are false. Submission separately disables linter.dupNamespace because two inherited children are already in Submission.Submission; their source text and declarations are preserved, and the root does not use them. These settings do not disable warningAsError or proof checking. The first stricter build exposed these compatibility diagnostics; this is recorded rather than described as an unqualified default-linter pass. The configured comparator supplies its own trusted build options and kernel/axiom checks independently of lakefile.lean.

Build and comparator outcomes, exact candidate SHA, and evidence path are recorded in the round summary after those operations. This audit itself does not assert a comparator result in advance.

## Reference use

`reference_use` contains exactly one entry:

```json
[
  {
    "source": "local-project",
    "snapshot": "/mnt/data/zhengyang-workspace/fermat-example/.humanize/github-theorem-prover/runs/20261006T035907Z-f6caab1a65/local-references/054ed6fe690aab0d",
    "project_commit": "9d6f2efe18bb6dd0747b7e00cae619ebb8cbe50b",
    "mathlib_commit": "db584cd6d46c92f209a44c0f1c829460d327499d",
    "findings": "The manifest pins the listed commits. project/Definitions/Def_WeierstrassCurve_RationalEnd.lean defines rationalHomSet by zero or polynomial fractions away from a finite exceptional set. The local rg search for HasHeight|surjective_of_mem_rationalHomSet|exists_mem_rationalHomSet_comp_eq_of_ker_le_of_xCoord_expand|exists_mem_rationalHomSet_isDualPair_and_add_eq_smul_id|dualIsogeny|inseparableDegree over project and mathlib/Mathlib/AlgebraicGeometry returned no matches (exit 1). The independently authorized recovered upstream closure at /mnt/data/zhengyang-workspace/fermat-example/.humanize/upstream-reference/6e837e75355538c7f80bab5b956861e86c4eacc2 supplies the actual height, factorization, division-polynomial and dual-trace proofs; every module matches its pinned hash. The root source and factorization/duality interfaces were inspected. No network search was used."
  }
]
```

## BitLesson Delta

- Action: none
- Lesson ID(s): NONE
- Notes: The knowledge base was read before each task; it contains no lessons.
