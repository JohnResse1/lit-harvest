# AI/LLM Extraction: Compliance Notes

> **Not legal advice.** This document records what the publisher agreements and platform policies
> actually say, so you can make an informed decision. Your institution's library or legal office is
> the authority for your situation. See the disclaimer at the end.

This document covers a feature that is **not yet implemented**. It exists so the design of the
eventual extraction layer starts from the agreements rather than from technical convenience.

## The core distinction

Everything before this step kept full text **on your machine**. Introducing an LLM creates one new
question that did not exist before:

```text
Does the content leave your machine?
```

The answer determines almost all of the risk, so the architecture is built around it.

| Route | Where content goes | Assessment |
| --- | --- | --- |
| **Local model** (Ollama, vLLM, llama.cpp) | Nowhere — stays on your machine | **Permitted path.** See below. |
| **External/cloud API** (OpenAI, Anthropic, …) | A third-party vendor's servers | **Requires express written permission.** See below. |

**Default is local.** An external API is opt-in and must be explicitly configured.

## What the Elsevier agreements actually say

These are the two documents this project was built against.

### API Service Agreement §2.4 — "Use with AI Systems; intermediary access"

AI use is **permitted**, but only if the AI System:

- is used in a **closed hosted (enterprise-grade) environment**, solely for the individual scholarly
  or research use of the Authorized User;
- **does not train the algorithm of an external AI System**;
- **does not share with and/or enable a third party access** to the Elsevier content, or any part of it;
- does not substantially or systematically reproduce, retain, store locally, redistribute or
  disseminate any Elsevier content — **including any generated responses** from an AI System;
- does not create a derivative work or service that could compete with, substitute for, or be
  reverse-engineered back into an Elsevier product.

§2.5 adds: **you are responsible and liable for any AI System you enable** to access the API Service.

### TDM provisions — the decisive clause

> "The ScienceDirect dataset and any TDM Output may be accessed, processed, or hosted by
> **third-party vendors retained by you only with the express written permission of Elsevier** and
> solely for the purposes as set out herein."

This is the sentence that settles the cloud-vs-local question. Sending full text to a commercial LLM
provider makes that provider a **third-party vendor processing the ScienceDirect dataset**. Under
these terms that requires **express written permission from Elsevier** — it is not covered by merely
holding an API key.

### TDM provisions — what you *may* do

> "text and data mine the ScienceDirect dataset via the API and **load and integrate the results
> (the TDM Output) on your internal system** for access by authorized users"

So the **extraction output (TDM Output) — not the raw dataset — may be retained and integrated
internally** for academic research, under these conditions:

- **Academic research purposes only.** No commercial use.
- External sharing of TDM Output requires this notice:
  > © Some rights reserved. This work permits academic research purposes only, distribution, and
  > reproduction in any medium, provided the original author and source are credited.
- **At project end you must immediately and permanently delete all copies of the ScienceDirect
  dataset** (including backups). TDM Output may be retained for academic research.
- No derivative work that competes with, substitutes for, or reverse-engineers an Elsevier product.

### Other clauses that shape the design

- §2.1: **do not use another user's credentials, and do not share yours.** This is why every user runs
  their own local instance with their own key.
- Term and termination: on termination, promptly and permanently delete all copies of content received
  via the API Service, and confirm in writing if asked.

## Direct answer: paid full text + local LLM

**Local extraction of paywalled content is the permitted path**, and it is permitted *because* the
content never leaves your machine. That is exactly what §2.4 and the third-party-vendor clause are
built around.

Two caveats worth stating plainly:

1. **"Local" must mean local.** A local model on your own machine, with no network egress of the
   document text, satisfies the intent. Routing the same text to a cloud endpoint does not become
   acceptable just because the caller is your script.
2. **The open-access question is separate.** OA content (CC BY and similar) does not carry these
   restrictions, so it may be sent to an external API. Paywalled content may not, absent written
   permission.

One reading caveat, stated honestly: §2.4 requires a "closed hosted (enterprise-grade) environment."
A model running entirely on your own machine is not literally "hosted," but it satisfies every
underlying condition more strongly than a hosted service would — no third-party access and no
external training. If you want certainty for your specific case, ask your library whether they read
purely local inference as inside §2.4.

## Design requirements this implies

These are binding constraints on the future extraction layer, not suggestions.

1. **Local-first default.** The default extractor target is a locally running model. No configuration
   ships that points at a cloud endpoint.
2. **Cloud is opt-in and gated.** Enabling an external API requires an explicit acknowledgement that
   the user has confirmed their entitlement permits third-party processing. The UI must state this in
   plain language before the first call.
3. **OA-only default for cloud.** Open-access content may use a configured external API. Paywalled
   content must not be sent externally unless the user has explicitly overridden the gate.
4. **Never train on the content.** Do not use a provider tier that retains inputs for training; the
   agreement forbids external training outright.
5. **Send the minimum necessary.** Extract per relevant passage/section rather than shipping whole
   articles. This reduces legal exposure, cost, and hallucination surface simultaneously.
6. **Provenance on every record.** Each extracted record carries source DOI, section, paragraph or
   table/figure, the source text span, confidence, and extractor version, so output is auditable and
   correctable.
7. **Human review is the default posture.** LLM output is a candidate annotation, not a fact. Nothing
   reaches a database or a publication without review.
8. **Dataset deletion stays supported.** `lit-harvest cleanup` already deletes raw full text while
   retaining derived results, which is the TDM end-of-project obligation. Extraction must not create a
   second copy of the raw dataset that bypasses it.
9. **No Sci-Hub or equivalent sources.** Excluded by project policy. Feeding unlawfully obtained
   content to any model, local or cloud, compounds the problem rather than avoiding it.

## Open-access content

For OA content (CC BY, CC0, and similar licences) the restrictions above do not apply in the same way,
because the licence already permits reuse and processing. Typical conditions are attribution and, for
some licences, share-alike or non-commercial terms. Record the licence alongside extracted data so
downstream use can respect it.

## Roadmap placement

This work belongs to the scientific-extraction phase (entities, relations, experimental events,
conditions, provenance), and the knowledge-graph and research-gap layers beyond it. It is explicitly
out of scope for the current release. See [ARCHITECTURE.md](ARCHITECTURE.md) and
[PARSING.md](PARSING.md) for how the deterministic layer is structured so this can be added without
disturbing it.

## Disclaimer

This document summarises agreements and policies as understood at the time of writing. It is not legal
advice, and agreements change. Before using any extraction feature on paywalled content, verify your
own entitlement and your institution's terms. When in doubt, use the local path, or ask your library.
