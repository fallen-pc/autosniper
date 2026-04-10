# DEC-008: evidence alignment is not repricing

Status: accepted
Date: 2026-04-10

## Decision
Checking that a curve tag lines up with the correct Autotrader and sold/Grays evidence is a separate task from changing the saved curve values.

Evidence-alignment work may:

- confirm that the mapped rows describe the intended vehicle family
- identify contamination, trim mixing, wrong body style, wrong fuel type, wrong transmission, or wrong series
- confirm that the saved tag/base is pulling from the intended evidence lanes

Evidence-alignment work must not, by itself, change saved curve prices unless repricing is explicitly requested or explicitly approved as part of the task.

## Reason
Tag alignment answers the question "are we comparing the same vehicle?" Repricing answers the question "should the saved values move?" Those are related but different decisions. Mixing them creates a high risk of accidental business-rule drift, especially during cleanup or audit work.

## Consequences
- A task that starts as evidence alignment should stop at alignment findings unless repricing is explicitly in scope.
- Alignment findings may justify a later repricing task, but they do not silently authorize one.
- Future curve-audit work should separate "same vehicle?" from "same value?" in both reasoning and implementation.
