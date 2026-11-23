# Understanding Self-Evolving Agents

[简体中文](README.md) · **English**

By shawn

What does an agent change as it learns from experience, and how can we test whether that change helps? This public source preview includes the Chinese-language manuscript (16 chapters and 7 appendices), figures, a reference index, and selected experimental records.

## Read the book and check the calculations

When a book PDF is available, its release lists the source commit and the PDF’s SHA-256 checksum. You can also build the book from the repository root. [Releases](https://github.com/Palmer-C/understanding-self-evolving-agents/releases)

The build requires Windows with Chinese fonts, XeLaTeX, latexmk, and biber. After a successful build, open `book/main.pdf`.

~~~powershell
powershell -ExecutionPolicy Bypass -File .\book\build.ps1
~~~

With Python 3, you can check the sample-size examples, review costs recorded in earlier experiments, or print the plan for a small E01 trial. All three commands run offline without model credentials.

~~~text
python calculations/audit_sample_size.py
python experiments/lab/cost_report.py
python -m experiments.lab.run_e01 --trial
~~~

Running untrusted candidate programs requires an isolated execution environment. This preview leaves that execution disabled.

For E03 split A, the archived summary reports 72/80 baseline successes, while the verdicts in the saved traces total 70/80. Comparisons that depend on this baseline are on hold until the discrepancy is resolved. All ten formal propositions remain open. E03v2 has only been checked offline against its saved artifacts. [Public materials and offline checks](analysis/README.md) · [Propositions](spec/propositions.md) · [Source index](references/sources.csv)

## Chapters at a glance

| Part | Chapter | Topic | What the chapter examines | Related experiments |
|---|---|---|---|---|
| I · Defining and evaluating self-evolution | [1](book/chapters/ch01.tex) | From autonomous execution to self-evolution | What evidence would show that an agent can change how it works? A falsifiable definition distinguishes that ability from completing a task. | — |
| | [2](book/chapters/ch02.tex) | Three timescales of self-evolution | Follow a change across a step, an episode, and a version to see how experience can carry over to another task. | — |
| | [3](book/chapters/ch03.tex) | Testing for sustained improvement | The four E01 conditions had the same episode quota. How many model calls did each use, and what can we conclude when an interval crosses zero? | E01 |
| II · Learning outside the model parameters | [4](book/chapters/ch04.tex) | From execution traces to reliable feedback | In an E02 example, the completion message says the top item was popped from a stack. Why does the code return the item but leave it on the stack? | E02 |
| | [5](book/chapters/ch05.tex) | Turning memory into reusable experience | How do memory format, capacity, and the model reading it affect transfer? The chapter identifies direct comparisons, conflicting records, and missing controls. | E03, E03c |
| | [6](book/chapters/ch06.tex) | From fixed rules to learned memory policies | Compare fixed rules, agent-directed organization, and learned policies for deciding what to store and how to retrieve it. | E03b |
| | [7](book/chapters/ch07.tex) | Optimizing instructions and context | How do fixed instructions, human revisions, and automated search compare under a fixed query budget? | E04 |
| | [8](book/chapters/ch08.tex) | Generating, verifying, and reusing tools and skills | How often must a task recur before the cost of building a reusable skill pays off? | E05 |
| | [9](book/chapters/ch09.tex) | Evolving workflows and multi-agent systems | Compare structures within a bounded search space and a common budget, including the costs of verification and failed branches. | E06 |
| III · Parameter learning and higher-level self-modification | [10](book/chapters/ch10.tex) | From external experience to model parameters | Use a regression set to check for lost capabilities and account separately for training and inference costs. | E08 |
| | [11](book/chapters/ch11.tex) | Experience, self-generated curricula, and reinforcement learning for agents | A curriculum can drift and a reward can be gamed. Even a majority of agreeing answers can be wrong. | E07, E09 |
| | [12](book/chapters/ch12.tex) | Code self-modification and meta-evolution | A constrained prototype explores changes to an agent’s own code-editing process and how to test whether those changes transfer. | E10 |
| IV · Long-running agents and systems engineering | [13](book/chapters/ch13.tex) | When to update | Compare event-triggered, periodic, and per-task updates under a resource budget. Does drift widen the differences? | E11 |
| | [14](book/chapters/ch14.tex) | Reliability, isolation, and recoverable updates | How much performance was lost, how long did detection take, and what can recovery restore? How often feedback needs external grounding remains open. | E12, E02b |
| V · Case studies and research limits | [15](book/chapters/ch15.tex) | Auditing experiments and designing transfer tests | Trace inputs, persistent artifacts, execution, and acceptance checks through saved cases, then design a controlled comparison for transfer. | Evidence from individual stages of E01–E05 |
| | [16](book/chapters/ch16.tex) | Theoretical limits and the research agenda | Ten research questions connect existing observations to the conditions under which they apply and the next comparison to make. | All |

## Licenses

| Material | Terms |
|---|---|
| Original manuscript, typeset PDF, original figures, research and analysis notes, and writing guidelines | Credit the author, indicate changes, and follow the noncommercial and share-alike terms. [CC BY-NC-SA 4.0](LICENSE-CC-BY-NC-SA-4.0.txt) |
| Author-written build scripts, offline analysis and experiment tools, experimental protocols and task sets, archived source snapshots, project-generated CSV and JSON data, and the source index | When redistributing these materials, retain the required notices and identify modified files. [Apache License 2.0](LICENSE-APACHE-2.0.txt) |

Third-party publications, upstream code, and embedded fonts are subject to their respective licenses. For the fonts used in the quantitative figures, see the [font notices and sources](book/figures/generated/FONT-NOTICES.md).
