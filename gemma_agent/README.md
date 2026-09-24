# Gemma 4 Developer Agent

Submission for [Google – The Gemma 4 Developer Agent Competition](https://www.kaggle.com/competitions/gemma-4-developer-agent):
a declarative Google ADK agent on `gemma-4-31b-it-qat-w4a16-ct` that fixes real
Python issues. Score = share of hidden tasks whose maintainer tests pass.

```
bundle/agent.yaml              root coder: 6 harness tools + 2 sub-agents
bundle/sub_agents/             code_analyzer (read-only localizer), reviewer (read-only patch check)
bundle/prompts/                system, analyzer and reviewer prompts
bundle/configs/sampling.yaml   shared generation config
build.py                       validates the bundle against the harness contract, writes dist/submission.zip
```

## Design

The two constraints that shape everything are the **32k context** and the
**all-or-nothing** grading (every test in the hidden test files must pass).

- **Exploration stays out of the coder's context.** Localization runs in
  `code_analyzer`, patch review in `reviewer`; both are `agent_tool`s with
  `skip_summarization`, so only their short, fixed-format report comes back.
- **Notes survive compaction.** The coder keeps its requirement checklist and
  status in `/tmp/notes.md`, outside the patch.
- **Match what a maintainer test asserts.** The coder reads existing tests for
  the code before fixing, implements the issue's names/messages literally,
  and runs the touched test files, separating regressions it caused from
  pre-existing failures with `git stash`.
- **Protocol failures are ruled out in the prompt.** Nothing under `tests/`
  (a new test file can collide with the hidden one and break `git apply`),
  scratch files only in `/tmp`, `timeout 240` on every test run,
  `submit_patch()` last.

## Build

```
python gemma_agent/build.py
kaggle competitions submit gemma-4-developer-agent -f gemma_agent/dist/submission.zip -m "<what changed>"
```

One submission per day, and only the 2 selected ones count, so every
submission should change one thing and be recorded in the log below.

## Submission log

| Date | Change | Public LB |
| --- | --- | --- |
