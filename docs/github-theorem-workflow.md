# GitHub theorem issues and solution PRs

The named flow `github-theorem-prover` extends the reference branch's reviewed
parent-to-child handoffs, isolated Lean worktrees, recursive scheduler, machine
comparator, independent reviewer comparator, and integration checks. Each theorem
node now also has an issue and a solution PR. The existing default flow is unchanged.

## Lifecycle

1. Freeze the original tracked Lean contract, root name/type, GitHub repository,
   target branch and initial revision. Verify that Git fetch, Git push and the
   GitHub API identify the same repository before starting proof work.
2. Review the root natural-language proof, then create its issue containing that
   proof, the exact Lean type, and the frozen project context.
3. At every accepted decomposition, create an issue for each child before starting
   any child worker. Each issue contains the complete parent-supplied proof, exact
   Lean type, parent/root links and prerequisite links. Update the parent with its
   child issues. Grandchildren use exactly the same mechanism.
4. Prove each node through the reference workflow's existing gates. A solution PR
   requires a passing machine comparator, a passing independent reviewer rerun,
   and successful local integration. The reviewer must report exactly the tracked
   declaration. Named new helpers belong in separate decomposition nodes; already
   accepted dependency declarations can be reused.
5. Publish the accepted solution with its natural-language proof, Lean contract,
   verification metadata, independent audit and dependency index in Git. Publish
   a dedicated PR and update the corresponding issue with its link.
6. Publish the root solution PR against the configured target branch after all
   active dependencies have verified solutions and PRs. It includes the complete
   integrated Lean solution and the proof records for every active node. Issues
   from obsolete decompositions remain available and are not closed by this PR.

An issue's natural-language proof is reviewed mathematics; its formal proof may
still be pending. The local DAG's `proved` state means locally verified and
integrated. It does not mean the remote PR has been reviewed or merged.

## PR bases and integration

Each child PR targets a dedicated immutable branch at that node's proof base.
This provides a stable comparison despite sibling work, parent dispatch commits,
or later integration repairs. The PR documents its prerequisite issues; its diff
may include the prerequisite proof overlays needed to prove that node.

The root PR targets `github_base_branch` (usually `main`) and delivers all locally
integrated solutions. Child PRs are independent review records; merging one into
its frozen base is not required to continue proving. The root PR carries closing
references for the entire problem's theorem issues. GitHub applies those references
when the root is merged into the repository's default branch; a different target
branch follows GitHub's normal closing-reference rules.

The workflow never automatically merges a PR, closes an issue, force-pushes a
branch, or updates the configured remote target branch. Ordinary pushes create
immutable publication branches. PR publication appends a documentation commit to
the exact accepted source tree; it does not edit the verified Lean files or the
canonical local problem branch. Publication branches live below:

```text
<prefix>/<project>/<run>/theorems/
  bases/<node-and-id-hash>
  solutions/<node-and-id-hash>
```

The inherited dispatch and result branches are also retained. Frozen bases and
result branches are intended to remain available for audit and resume.

## Configure and run

Use a fresh run in the target **Lean problem repository**, with a clean Git tree,
a tracked `Challenge.lean` (or configured contract file), pinned Lean dependencies,
the project comparator, and the reference workflow's Humanize prerequisites. Git
must have noninteractive fetch/push access and `gh` must have permission to read
the repository and write its issues and PRs. Remote URLs must not contain tokens.

Copy `config.github-theorems.example.yaml` to the problem repository and set:

| Setting | Meaning |
| --- | --- |
| `github_repository` | Explicit `owner/repository`; must match fetch and push remotes |
| `github_workspace_remote` | Existing Git remote, usually `origin` |
| `github_base_branch` | Existing remote branch receiving the complete root solution |
| `github_root_lean_name` | Actual fully qualified root declaration, not a module name |
| `github_root_lean_statement` | Exact single-line Lean type expression, without a declaration or proof |
| `github_contract_file` | Tracked Lean source containing the original problem context |
| `lean_target` | Candidate Lean source file |
| `comparator_command` | Existing comparator that checks the exact frozen problem |

For example, after installing this checkout as `user/recursive_lean_prover`:

```sh
hmz check user/recursive_lean_prover:github-theorem-prover
hmz exec -f user/recursive_lean_prover:github-theorem-prover \
  -c github-theorems.yaml \
  -a cli=codex,permission=auto,web_search=off \
  -a cli=codex,permission=auto,web_search=off \
  "Prove the selected problem described in PROBLEM.md using the frozen Lean contract."
```

Select worker/reviewer models through the existing Humanize agent configuration.
For the Zhengyang workspace, model execution must use the local Codex authentication
and API configuration at `/home/zhengyang/.codex`; do not substitute a provider when
it is missing. Never use `rust.cat` endpoints. Keep web search disabled for First
Proof Second Batch Humanize. This variant retains the reference workflow's direct
Lean-Eval problem acquisition and reference snapshots; disabling web search does
not replace those prerequisites or add an offline problem-import mode.

The flow handles one root theorem per invocation. For multiple independent roots,
run it once for each selected problem with the correct root contract. This workflow
does not turn an unproved mathematical claim into a solved claim merely by opening
an issue or PR.

## Resume and evidence

Rerun the same command with the same task, configuration and problem repository.
The run records its repository/contract identity in `github-workflow.json`, stores
issue/PR URLs in `dag.json`, and displays them in `DAG.md`. Each node retains a
`github-solution.json` receipt naming the exact publication commit before any remote
push. Its proof records are committed below `proofs/github/<run>/` on solution branches.

Issues and PRs carry stable identity markers. The publisher reads all pages of
remote records before creating one, including closed records. An interrupted
successful API call is therefore reconciled on resume. A process lock prevents
two publishers for the same local run. Changed remote heads, conflicting markers,
changed root contracts, or a PR closed without merging stop publication for explicit
resolution. A GitHub outage preserves accepted mathematics; resuming republishes
the checkpoint instead of proving it again. Oversized issue bodies fail explicitly
instead of truncating the required proof.

## Tests

With Python 3.12+, Humanize and its dependencies available:

```sh
python -m unittest discover -s tests -v
```

Publication tests use real local bare Git repositories and a simulated GitHub API.
They cover recursive issues, root and child PRs, dependency links, unchanged Lean
source, retry after a lost successful response, durable publication receipts,
unverified-proof rejection, and protection against moved remote branches. They do
not launch model sessions, run Lean, or publish to a live GitHub repository.
