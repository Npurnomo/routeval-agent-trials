# Preserved participant solutions

These files are the completed initial-session runtime implementations from the
October 20 pilot, copied byte-for-byte. provenance.json pins their source and
public digests. They are learning examples for these fixed contracts. They are
not a general untrusted-input boundary or production deployment tool.

The chair-authored wrapper supplies portable paths, new output directories,
common receipts and real process logs. It does not change the decision code:

```sh
python tools/run_reference.py integration stdlib --output work/integration-stdlib
python tools/run_reference.py integration routeval --output work/integration-routeval
python tools/run_reference.py evaluation stdlib --output work/evaluation-stdlib
python tools/run_reference.py evaluation routeval --output work/evaluation-routeval
```

Use the interpreter from the environment containing Routeval 0.1.1 for package
examples. The two standard-library examples do not import it. Each command
requires a new output path. A batch exit 0 means collection completed; inspect
submission.json for the separate accept/reject/invalid policy recommendations.
The wrapper preserves actual child exits, output and errors. Package-native
comparison receipts remain with the generated evidence.

Run the local receipt checker described in docs/participate.md after a replay.
The original integration implementations preserve charged failures and known
partial ledgers. Evaluation examples check fixed owner requirements in caller
code as well as baseline comparisons. The package example uses only root public
exports and the documented compare CLI. It does not parse terminal tables.

The original module comments may include pilot timing constants or explanatory
text. Replays are marked as chair-authored reproductions and are not new agent
sessions. Original reports, revision snapshots and command logs remain in the
local study archive. The public study publishes its scoring summary, method,
feedback, input hashes and unmodified runtime code.
