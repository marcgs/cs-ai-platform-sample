# RCA test cases

`src/rca_evals/cases.jsonl` holds the RCA agent's 50 test cases: the engineer's report sent to the agent, and the answer key an evaluation compares the diagnosis with. All of it is synthetic.

| Cases | What they test |
|---|---|
| `SC-001` to `SC-018` | Clean incidents: one fault, clear evidence |
| `SC-019` to `SC-050` | Challenge cases in eight categories: overlapping faults, no fault found, a fault outside the catalog, a missing machine identifier, prompt injection in a logbook entry, a faulty sensor, a data gap and a nuisance alarm |

Each case has:

- `input`: the message sent to the agent.
- `expected`: the machine and the failure mode to find (`unknown` when the right answer is to abstain).
- `truth`: the category, the decisive evidence references, accepted alternative failure modes, failure modes that should be ruled out, confirming checks, and the markers of planted instructions.
- `split`: `train` or `test`, assigned per machine so a machine never appears in both.

The cases are generated from the seed scenarios in `packages/diagnostics-domain`. Don't edit them by hand; after changing the seed data, regenerate them:

```bash
uv run generate-seed-data
uv run python -m rca_evals.manifest
```

A test checks that the committed file matches the generator, and regeneration keeps existing train/test assignments.

Evaluation itself is being rebuilt the way Foundry documents it. The earlier, self-built harness and its metrics are in the `before-cleanup` tag.
