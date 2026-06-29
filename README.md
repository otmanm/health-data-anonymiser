# Health Data Anonymiser

Offline prototype for cleaning sensitive health notes before they leave the machine.

This repo is my first public artifact in healthcare data privacy: a local macOS prototype for removing protected health information from `.md` and `.txt` clinical notes before the text reaches an external model, SaaS tool, or shared workflow.

It is not a medical device, not a compliance guarantee, and not a replacement for expert privacy review.

## Project intent

The original idea was broader than a single local tool.

Health data does not look the same everywhere. Forms, identifiers, dates, languages, and privacy rules vary by country and region. I wanted to explore a health data anonymiser that could eventually reason across the contexts most relevant to my own work and life: Europe, the United States, Belgium, Spain, Morocco, and adjacent multilingual workflows.

That larger ambition is not fully implemented in this repo.

The public prototype is the first step: clean sensitive health text locally, prove the data minimisation principle, and avoid sending raw clinical notes into external systems by default.

## Current status

This project is now part of a broader healthcare data privacy track.

After building this prototype, I began contributing to [OpenMed](https://github.com/maziyarpanahi/openmed), a larger open-source local-first healthcare project. My contributions there focus on de-identification reliability, date handling, test coverage, and privacy edge cases.

## Relationship to OpenMed

This repo is a small standalone prototype.

OpenMed is the larger ecosystem where I now contribute to production-grade healthcare tooling. My work there includes fixes and issue analysis around medical date de-identification, interval preservation, deterministic behavior, and CI coverage.

I did not build OpenMed and I do not own it. I built this prototype first, then found a stronger open-source project working on the same problem and started contributing where the work could matter more.

## OpenMed contribution direction

My contribution direction is deliberately boring:

- date handling
- format preservation
- deterministic behavior
- CI coverage
- privacy edge cases

These are small-looking problems with large privacy implications: in clinical text, dates can identify people, break timelines, or create misleading de-identified records.

## Limitations

This tool is a prototype.

Do not use it as your only privacy control for real patient data. Always review outputs manually. De-identification reduces risk, but it does not eliminate all re-identification risk.

## Original prototype

Local macOS prototype built around NLM Scrubber, the NIH de-identification tool. Drag and drop `.md` or `.txt` health notes to remove names, dates, IDs, locations, and other protected data before using the cleaned text elsewhere.

The point of the prototype is local-first data minimisation: remove what an external system does not need before any sensitive text leaves the machine.
