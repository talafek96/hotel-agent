# Development Rules

## Quality Checks (run after every code change)
```bash
python -m uv run ruff check src/ tests/
python -m uv run ruff format --check src/ tests/
python -m uv run mypy src/hotel_agent/
python -m uv run pytest
```

## Non-Obvious Constraints
- `PYTHONIOENCODING=utf-8` required on Windows for CLI commands (Hebrew/Japanese text).
- Project path contains spaces — always use `pathlib.Path`, never hardcode separators.
- Every new module must have corresponding tests. Mock LLM calls, use temp DBs.
- Rule-based logic for comparisons/alerts — do NOT use LLM where deterministic rules suffice.
- Keep AGENTS.md files short. Only document things not obvious from reading the code.
- Update this file when the user corrects you about something.
- Update README.md when adding new features, commands, config options, or setup changes.

## User Preferences
- Cares about: low cost, reliability, easy maintenance, clear alerts.
- Does NOT want: fancy UI, over-engineered frameworks, AI for AI's sake.
- Wants to switch between LLM providers easily.
- Commit messages: concise summary line, bullet-point body. No paragraphs. Never mention Devin or Co-Authored-By.
- New work goes on feature branches: `usr/<github-username>/<branch_name>` (e.g. `usr/tal-afek/pipeline-scheduler`).
- **NEVER merge a PR without explicit approval or request from the user.** PRs are for review — the user decides when to merge.

## No AI Credit

Never attribute work to yourself or to any AI agent, tool, or assistant. This applies to every artifact you produce or modify.

- NEVER add "Co-Authored-By" lines referencing any AI agent or bot in git commits.
- NEVER add "Generated with", "Created by", "Built with", "Powered by", or similar AI attribution to git commits, PRs, code comments, documentation, READMEs, changelogs, or any other output.
- NEVER add badges, links, sections, or footnotes crediting an AI tool or agent.
- NEVER add file headers or authorship lines that reference an AI tool.
- NEVER include `noreply@` email addresses associated with AI bots in commits.
- Git commit messages must contain only the actual change description — no agent attribution of any kind.

Before completing any task, scan your output for:
- "Co-Authored-By" lines referencing any AI or bot
- "Generated with" / "Created by" / "Built with" / "Powered by" followed by an AI tool name
- Any mention of an AI agent name as an author or contributor
- Badges or links that credit an AI tool
- `noreply@` email addresses associated with AI bots

If any of these are present, remove them before finishing. No exceptions.

## Writing Rules — Keep Them Concise

Rules consume agent context in every session. Verbose rules dilute attention and waste context budget.

- **Aim for actionable checklists, not documentation.** If a rule reads like an essay, it's too long.
- **Every line should be an instruction the agent can act on.** Remove explanations of *why* — agents need *what* and *when*.
- **Consolidate** — 5 crisp bullet points beat 40 lines of prose.

## Blast Radius

Before making any change, estimate its blast radius — how many files it touches, how complex the diff will be, and how hard it is to revert.

- **Estimate first:** How many files? (>5 = break it up.) How complex? Can you revert cleanly?
- **Small atomic changes.** One commit = one purpose. Each independently revertable.
- **State your approach** in one sentence before coding. List files you expect to modify.
- **If >2x longer than expected**, STOP and reassess. Do not push through.
- **Simple > clever.** Do not build abstractions for one-time problems. When in doubt, do less.
- **Know your limits.** If the scope exceeds what fits in context, say so. Don't guess.

## Pitfalls Discipline

Maintain a `PITFALLS.md` file in every project. This is the knowledge base of things that went wrong and how they were fixed.

### Before complex work

- Check `PITFALLS.md` for entries related to the area you're touching.
- Search git log for relevant fixes: `git log --oneline --grep="<keyword>"`.
- If a past pitfall is relevant, factor it into your approach before writing code.

### After fixing a bug

- Add an entry: **symptom** (what you observed), **cause** (root cause), **fix** (what resolved it), **commit** (reference).
- Keep entries concise — 2-4 lines each.

### Promotion

- If a pitfall recurs across projects, promote it to a global rule in `AGENTS.md`.
- If a pitfall can be prevented structurally (test, hook, validation), add the guardrail and note it in the entry.

## Prior Art

Before building anything non-trivial, search for existing solutions first.

1. **In the codebase** — check for existing utilities, helpers, patterns.
2. **In dependencies** — check package.json/Cargo.toml/requirements.txt before adding anything new.
3. **On the web** — use `duckduckgo-search` skill for established packages and patterns.
4. **On GitHub** — use `github-search` skill for repos with stars, license, and freshness info.

**Evaluate:** maintenance status, adoption, scope fit, license, security.

**Always report** what you found: "Found X, reusing it" or "Searched for X, nothing suitable, building custom."

## Verification Ladder

Build automated verification at multiple layers. Set up test infrastructure before feature code.

### Layers
0. **Compile** — zero warnings (`-Wall -Wextra` or equivalent)
1. **Unit** — each function/API works correctly (PASS/FAIL/SKIP)
2. **Integration** — multiple functions compose correctly
3. **Performance** — baselines in machine-readable file, warn on >50% regression
4. **End-to-end** — real application smoke test, automated

### Principles
- Every test proves three things: correct **outcome**, correct **mechanism**, clean **side effects**.
- Test the negative path — invalid inputs must produce clean errors, not crashes.
- Distinguish PASS, FAIL, and SKIP — environment problems are SKIPs, not FAILs.
- Automate the most important check first.
- Pre-commit: build must succeed. Pre-push: fast test subset must pass.

## Verify Your Work

Test everything you create before declaring done. Do not assume correctness — prove it.

- **Run the code.** If it produces output, inspect it. If it has side effects, confirm they occurred.
- **Pause for what only the user can provide** — API keys, OAuth, credentials, policy decisions.
- **State what was tested** and what remains untested. Never say "should work."

## Document Lifecycle

Every project has exactly three documentation tiers. No more.

- **Tier 1: Rules** (`AGENTS.md`) — conventions, testing requirements, critical rules. Max 200 lines. No changelogs or history.
- **Tier 2: Reference** (`HANDOFF.md`) — current state, how to build/test, what's next. Updated in-place after every behavior-changing commit.
- **Tier 3: History** (`CHANGELOG.md`) — what changed and when. Append-only.

### Rules
- Never create a document to flag that another is stale — fix the stale one.
- Never duplicate information across tiers.
- If a document has no owner or update trigger, delete it.
- After every behavior-changing commit, `HANDOFF.md` must be accurate.

## Document Progress

For tasks with 3+ steps or 2+ files, write progress to disk. Context compacts and sessions end — files survive.

- **Before starting:** Plan what you'll do in the todo list.
- **After each step:** Mark the todo complete. Update `HANDOFF.md` if behavior changed. Commit.
- **Do NOT rely on conversation memory.** The todo list and `HANDOFF.md` are your memory.
- Never create append-only logs that grow unboundedly. `HANDOFF.md` is edited in-place to reflect current state. History goes in `CHANGELOG.md`.

## Continuous Improvement

When asked to improve or harden a codebase, follow these phases in order:

1. **Discovery** — Audit for code smells, error handling gaps, edge cases, security issues, missing tests, docs gaps, performance problems. Use tools to verify — never guess. List findings with file path, line number, and severity.
2. **Planning** — Group by category, rank by impact, present plan before implementing. One change per commit. Flag anything that could break existing behavior.
3. **Validation** — Confirm each problem exists. Check existing tests. Read git history for context. Do not refactor based on speculation.
4. **Implementation** — Match existing conventions. One change at a time. Simple > clever. Do not over-engineer or rewrite working code without a discovered reason.
5. **Testing** — Write/update tests for every change. Run full suite after each group. Test happy path AND failure modes.
6. **Documentation** — Update docs where behavior changed. Clear commit messages.
7. **Self-review** — Would you approve this in code review? If unsure, fix it or flag it.

## Improve the Process

The task is never just the task. Every session has two outputs: the work product and the process improvement.

### Before finishing a session:
- **Did you hit friction?** Fix the system — add a check, update a doc, improve a script. Don't just work around it.
- **Did you make a mistake?** Add a guardrail — a test, a hook, a validation — so the next agent can't repeat it.
- **Did you discover something useful?** Write it where it'll be found — HANDOFF.md, AGENTS.md, a tool. Not in conversation.
- **Are the rules wrong?** Fix them. The methodology is code. It has bugs. Ship fixes.

### What this looks like:
- Spent 20 minutes debugging an environment issue? Add it to the pre-flight checklist.
- Forgot to update HANDOFF.md? Add a pre-commit check for it.
- Found an undocumented behavior? Add it to HANDOFF.md, not a progress log.
- A test didn't catch a regression? Write the test that would have.

### Why:
Each session that improves the process makes the next session easier. This compounds. A project that improves its workflow every session gets faster over time, not just bigger.

## Session Resilience

You don't have memory. These files do. Everything you learn this session is lost when it ends.

- **Treat every session as your last.** Write state to disk continuously, not just at the end.
- **HANDOFF.md is your memory.** After every meaningful change, update it with current state, what works, what's next.
- **PITFALLS.md captures lessons.** When you fix a bug or discover non-obvious behavior, write it down: symptom, cause, fix.
- **CHANGELOG.md tracks history.** One paragraph per milestone. Append-only.
- **The todo list is your plan.** If it's not in the list, it doesn't exist. If context compacts, the list survives.
- **Never assume the next agent has context.** Write as if someone with zero knowledge will continue your work.
- **The question isn't "did I complete the task?"** — it's "would the next agent thank me for how I left this project?"

## Stay Motivated

The todo list is the definition of completeness. Before stopping, check it.

### "Done" means ALL of these:
- All todo items completed
- Tests pass
- Changes committed
- `HANDOFF.md` accurate

### Before stopping:
- Pending todo items? **Keep working.**
- Finished one step? **Start the next.**
- Hit an error? **Debug it.**
- About to ask a question you could answer by searching? **Search first.**

### If unsure whether you're done:
Invoke `/motivation` — it checks git, HANDOFF.md, build, and tests, then reports what's objectively incomplete.

## Task Formation

### Decompose First

When you receive a request, break it down before coding:

1. **Identify goals** — what are we trying to achieve and why? State the intent, not just the action.
2. **Break into tasks** — each goal becomes actionable tasks with concrete steps.
3. **Write it in the todo list** — the list is the plan. If it's not in the list, it doesn't exist.
4. **Order by dependency** — what must happen first? What's parallel?

Every goal has a "why." Every task has a "done" condition.

### Writing Tasks

- **Define "done"** as one concrete command with one observable outcome before writing any code.
- **Reference code by name, not line number.** "After the declaration of `g_handle_map`" not "after line ~2113."
- **Every task has a pass condition** written before work starts — a specific, verifiable check.
- **Dependency graphs are explicit.** If B depends on A, draw it.
- **Tasks are sized for one session.** If it can't be completed, tested, and committed in one sitting, break it down.

### The Commit Loop
1. State what you're changing in one sentence
2. Write or update the test
3. Make the change
4. Run the test — if it fails, go back to 3
5. Run the full fast suite
6. Update `HANDOFF.md` if behavior changed
7. Commit

## Python UV

ALWAYS use `uv`. NEVER use `pip`, `pip install`, `virtualenv`, `venv`, `pyenv`, `conda`, or `poetry`.

- **Scripts:** PEP 723 inline metadata + `uv run script.py`
- **Projects:** `uv init`, `uv add`, `uv sync`, `uv run`
- **Virtualenvs:** `uv venv` (never `python -m venv`)
- **Global tools:** `uv tool install` (never `pip install --user` or `pipx`)
- If an existing project uses pip/requirements.txt, follow its conventions — do not migrate without asking.

## Simplicity Bar

Every change has a complexity cost. Weigh it against the improvement before keeping it.

- **Removing code that preserves results is always a win.** Fewer lines, same outcome = strictly better. Keep it unconditionally.
- **Marginal gains do not justify ugly complexity.** A 0.1% improvement that adds 20 lines of hacky code is not worth it. A 0.1% improvement from *deleting* code is definitely worth it.
- **Equal results + simpler code = keep.** If a refactor yields the same behavior with less complexity, that is a positive outcome, not a wash.
- **Before adding code, ask:** "Would I accept this in a code review if someone else wrote it?" If the answer is "only because it technically works," don't ship it.
- **Complexity is a liability.** Every line you add must be read, maintained, and debugged by the next agent. Earn each line.

> *"All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome -- that's a simplification win."*
> -- [karpathy/autoresearch](https://github.com/karpathy/autoresearch/blob/master/program.md)

### Examples

| Change | Outcome | Verdict |
|--------|---------|---------|
| Add 30-line caching layer | 2% speedup | Weigh carefully -- is 2% worth 30 lines? |
| Delete unused abstraction | Same behavior | **Keep** -- simpler with no downside |
| Inline a helper used once | Same behavior, fewer indirections | **Keep** -- simplification win |
| Add retry logic with backoff | Fixes flaky failures | **Keep** -- complexity is justified by reliability |
| Add feature flag framework | Supports one toggle | **Reject** -- over-engineering for one use case |

## Autonomous Persistence

Do not pause to ask the human if you should continue. Keep working until the task is done or you are explicitly stopped.

- **Never ask "should I keep going?"** The human may be away, asleep, or busy. They expect you to continue working autonomously. If there is more work to do, do it.
- **Never ask "is this a good stopping point?"** If the todo list has pending items, it is not a stopping point. Period.
- **Only pause for what you genuinely cannot provide yourself** -- credentials, API keys, policy decisions, ambiguous requirements. Everything else, figure it out.
- **If you run out of ideas, think harder.** Re-read the codebase for angles you missed. Re-read the requirements. Try combining previous near-misses. Try a more radical approach. Do not give up and ask the human for inspiration.
- **Exhaust your tools before asking.** Search the codebase, search the web, read documentation, read git history. The answer is almost always findable.

> *"Do NOT pause to ask the human if you should continue. Do NOT ask 'should I keep going?' or 'is this a good stopping point?'. The human might be asleep, or gone from a computer and expects you to continue working indefinitely until you are manually stopped. You are autonomous. If you run out of ideas, think harder -- read papers referenced in the code, re-read the in-scope files for new angles, try combining previous near-misses, try more radical architectural changes."*
> -- [karpathy/autoresearch](https://github.com/karpathy/autoresearch/blob/master/program.md)

### Examples

| Situation | Wrong | Right |
|-----------|-------|-------|
| Finished a subtask, more remain | "Should I continue to the next step?" | Start the next step immediately |
| Hit an error you haven't seen | "I'm stuck, what should I do?" | Search error message, read docs, try alternatives |
| First approach didn't work | "Want me to try something else?" | Try something else |
| Unsure which of two valid approaches to use | "Which do you prefer?" | Pick the simpler one, note the tradeoff, keep moving |
| Need an API key you don't have | Ask the human | **Correct** -- this is genuinely blocked |

## Revert on Failure

When making speculative changes, use git as a safety net. Commit a known-good state, experiment, measure, and revert if the change does not improve things.

- **Commit before experimenting.** Always have a clean commit to revert to. Never experiment on a dirty working tree.
- **Define "better" before changing code.** Know your success metric (test passes, performance improves, error disappears) before making the change. If you cannot state the metric, you are not ready to change code.
- **Measure after every change.** Run the relevant check immediately. Do not batch multiple speculative changes -- test each one individually.
- **Keep what improves, revert what doesn't.** If the metric improved, commit and advance. If it didn't, `git checkout -- .` or `git reset --hard` back to the last good state. Do not accumulate failed experiments in the working tree.
- **If a change crashes, use judgment.** Trivial fix (typo, missing import)? Fix and re-run. Fundamentally broken idea? Revert immediately and move on.
- **Never push through.** If you have tried the same approach 3 times without improvement, abandon it and try a different angle.

> *"If val_bpb improved (lower), you 'advance' the branch, keeping the git commit. If val_bpb is equal or worse, you git reset back to where you started."*
> -- [karpathy/autoresearch](https://github.com/karpathy/autoresearch/blob/master/program.md)

### The Loop

```
1. git commit   (baseline / known-good state)
2. Make one change
3. Run the check (test, build, benchmark)
4. Improved? -> git commit (new baseline)
   Same or worse? -> git reset --hard HEAD
5. Go to 2
```

### Examples

| Scenario | Action |
|----------|--------|
| Refactoring a function, tests still pass after change | **Commit** -- new baseline |
| Trying a different algorithm, tests fail | **Revert** -- go back to working state |
| Build breaks due to missing import you just introduced | **Fix the typo and re-run** -- trivial crash |
| Third attempt at an optimization yields no gain | **Abandon the approach** -- try something else |

## Output Discipline

Do not flood your context with raw command output. Redirect to files and extract only what you need.

- **Redirect verbose commands to files.** Use `command > output.log 2>&1` for anything that produces more than a screenful. Never pipe long output into your context window.
- **Extract with targeted reads.** Use `grep`, `tail`, `head`, or specific line reads to pull out the information you need. Do not read entire log files when one line answers the question.
- **Never use `tee` for long-running commands.** It floods your context with the same output you saved to disk. Redirect, then read selectively.
- **Diagnose failures from the end.** If a command fails, `tail -n 50 output.log` gets you the stack trace. Do not read from the top.
- **Delete temporary output files when done.** Log files are diagnostic tools, not artifacts. Clean up after yourself.

> *"Run the experiment: `uv run train.py > run.log 2>&1` (redirect everything -- do NOT use tee or let output flood your context). Read out the results: `grep '^val_bpb:\|^peak_vram_mb:' run.log`"*
> -- [karpathy/autoresearch](https://github.com/karpathy/autoresearch/blob/master/program.md)

### Examples

| Task | Wrong | Right |
|------|-------|-------|
| Run tests | `pytest` (500 lines flood context) | `pytest > test.log 2>&1 && tail -n 20 test.log` |
| Check a metric | Read entire 10,000-line log | `grep "^accuracy:" run.log` |
| Debug a crash | `cat output.log` | `tail -n 50 output.log` |
| Build a project | `make` (scrolling build output) | `make > build.log 2>&1 && echo "exit: $?"` |
