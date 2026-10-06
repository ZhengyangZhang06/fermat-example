# GitHub theorem issues and solution PRs

The named flow `github-theorem-prover` extends the reference branch's reviewed
parent-to-child handoffs, isolated Lean worktrees, recursive scheduler, machine
comparator, independent reviewer comparator, and integration checks. Each theorem
node now also has an issue and a solution PR. Each problem run has its own status
website. The existing default flow is unchanged.

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
| `github_status_publish` | Publish the status website to Pages (default `true`); local HTML is always generated |
| `github_status_branch` | Dedicated Pages source branch, default `gh-pages`; must differ from the solution target |
| `github_status_interval` | Seconds between hosted snapshots, default/minimum `600` |

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

## Status website for every problem

Each run generates a responsive static website as soon as its local state exists,
including before GitHub preflight succeeds. The page shows:

- Current problem phase and counts of verified, integrating and pending theorems.
- The theorem hierarchy, dependency links and expandable exact Lean statements.
- Issue and solution PR links, plus the last recorded PR merge state and check time.
- Search, status filters and access to earlier decompositions.
- Snapshot time, running/finished/paused state, and a warning for stale running snapshots.

Proof verification and GitHub merge status are separate. Only the active dependency
graph contributes to completion. Missing or cyclic dependencies cannot report a
verified problem. The website publishes an explicit subset of DAG fields; local
paths, agent prompts, authentication and raw process logs are not included.

Local HTML updates on every saved DAG change. The page reloads every minute unless
someone is reading an expanded theorem or using the filters. It works from disk or
a basic static web server, with no external scripts, fonts, build tools or browser
credentials. Find the local page at the path printed by the workflow, or beneath:

```text
<run_dir>/website/theorem-status/<problem-key>/<run>/index.html
```

For a local demonstration with clearly labelled sample data:

```sh
python scripts/preview-status.py /tmp/proof-status-preview
python -m http.server 8000 --directory /tmp/proof-status-preview
# Open http://localhost:8000/theorem-status/index.html
```

Hosting is enabled by default. The publisher pushes only website files to a
separate `gh-pages` branch, enables branch-based Pages when it is not configured,
and uses the Pages API's actual URL (including any existing custom domain). Each
problem run lives under `/theorem-status/<problem-key>/<run>/`, with a shared index
at `/theorem-status/index.html`. Issues and PRs link to the status website when its
hosting URL is available. A concurrent run adds its page to the latest website
branch without overwriting earlier problem pages or an existing homepage.

The first snapshot publishes before proof work; later hosted updates run in the
background every ten minutes by default, with a final snapshot when the run exits.
They also refresh recorded PR states. The browser displays the latest deployed
snapshot; Pages builds are asynchronous, so a pushed source revision is not a claim
that deployment has completed. Once the run stops, its website remains a timestamped
snapshot; resume the workflow to refresh it again.

Enabling a new Pages site requires permission to manage Pages. An existing site
must use the configured website branch and its root directory; the workflow will
not change an unrelated site's publishing settings. These source and permission
requirements follow the [GitHub Pages REST API](https://docs.github.com/en/rest/pages/pages#create-a-github-pages-site).
GitHub's [Pages source documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)
describes deployment from a branch. The website namespace has an ownership marker;
an unrelated existing `theorem-status/` directory is not replaced.

An unavailable host, permission failure or conflicting Pages configuration does
not invalidate a proof or stop mathematical work. Local pages continue to update;
the next scheduled publish retries, and `github-status.json` records the hosting
result. Set `github_status_publish: false` for a local website only.

## Resume and evidence

### Local repository problems

Set `local_problem: true` for a supplied local Lean contract. This opt-in mode
freezes the tracked `github_contract_file` at the run's source revision instead
of acquiring a Lean-Eval problem. It does not fabricate leaderboard metadata.
The existing local `lake-manifest.json` must pin mathlib and its checkout must
be clean at that revision. Project and mathlib reference clones are frozen for
the run and checked for changes on resume.

In this mode each stage records one `reference_use` entry for `local-project`,
citing actual files inside that snapshot. The three Lean-Eval reference corpora
are not required. All statement, comparator, independent review, decomposition,
issue/PR and integration gates remain unchanged. The default Lean-Eval mode
still requires all three original corpora. A real project comparator must be
provided; local acquisition does not waive verification.

Run the flow from an isolated directory (for example a clone under
`.humanize/flows/math-lean-flow`) if Humanize's dependency installation lives under
the same broad workspace parent as the original flow checkout. Humanize unloads
modules beneath a flow's parent after loading it; sharing that parent with Python
site-packages can otherwise break configuration type discovery.

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

Website tests additionally exercise HTML escaping, dependency-aware completion,
local updates, remote PR-state snapshots, initial/final publication, preservation
of other pages, concurrent pushes and recovery from hosting failures.
