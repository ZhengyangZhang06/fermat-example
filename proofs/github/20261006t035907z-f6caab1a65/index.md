# Theorem solutions

Local proof acceptance and GitHub merge status are separate.

All four solution PRs are now merged and their issues closed. The root PR below
delivers the combined solution to `main`; child PRs merged into their frozen review
bases. "Requires" records workflow prerequisites. The reviewed final root prose
documents its actual upstream dependencies and the unused historical children.

| Node | Issue | PR | Requires |
| --- | --- | --- | --- |
| root | https://github.com/ZhengyangZhang06/fermat-example/issues/1 | https://github.com/ZhengyangZhang06/fermat-example/pull/8 | root.no_integer_scalar_relation-a1, root.trace_norm_uniqueness-a1, root.finite_kernel_torsion-a1 |
| root.finite_kernel_torsion-a1 | https://github.com/ZhengyangZhang06/fermat-example/issues/4 | https://github.com/ZhengyangZhang06/fermat-example/pull/5 | none |
| root.no_integer_scalar_relation-a1 | https://github.com/ZhengyangZhang06/fermat-example/issues/2 | https://github.com/ZhengyangZhang06/fermat-example/pull/6 | none |
| root.trace_norm_uniqueness-a1 | https://github.com/ZhengyangZhang06/fermat-example/issues/3 | https://github.com/ZhengyangZhang06/fermat-example/pull/7 | root.no_integer_scalar_relation-a1 |
