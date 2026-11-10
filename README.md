# simple-editor

**English** · [Русский](README.ru.md)

A translation editing workflow for an AI assistant, with plain Markdown instructions and Python tools for assembling reviewed chapters into one FB2 ebook. It supports different genres and language pairs; each work keeps its own terminology, style references, and editorial decisions.

This is a repository of instructions and command-line tools. The assistant edits the text; the Python scripts extract saved source pages and assemble the reviewed result.

## Requirements

- Python 3.9 or later. The scripts use only the standard library.
- An AI assistant that can read and write local files and run commands. Source research also requires web access.
- Git for cloning and version history.

## When using Codex: reasoning must be at least high

For translation editing in this project, set reasoning effort to **at least `high`**. This is a project requirement. Your selected model must support that level.

Set the following in your Codex configuration:

```toml
model_reasoning_effort = "high"
```

The setting is documented in the [official OpenAI documentation](https://developers.openai.com/codex/config-reference/). If your interface has a reasoning effort selector, choose `High` or a higher supported level. For other assistants, use their available thorough reasoning setting and retain all editorial checks; equivalence between providers' effort levels has not been tested.

## Getting started

```sh
git clone https://github.com/szmelikyan/simple-editor.git
cd simple-editor
```

Open this folder in your assistant. Have it read [AGENTS.md](AGENTS.md) and the [translation editing workflow](.agents/skills/translation-edit/SKILL.md). If your assistant does not load skills automatically, it can read these Markdown files directly.

Example request:

> Edit this translation. Preserve its meaning, narrative voice, terminology, and formatting. Store the work in projects/my-book and update edited.fb2 after each fully reviewed chapter. Ask me about unresolved ambiguities before choosing a disputed reading.

Provide the translation and, when available, the original. Without the original, the assistant checks against the supplied translation and must state that limitation. Translation from scratch is a separate request.

## Files for each work

Keep different works in separate `projects/<slug>/` folders:

| Path | Purpose |
| --- | --- |
| `profile.md` | Languages, genre, audience, style references, and chapter order |
| `glossary.tsv` | Approved terms, context, and verification status |
| `decisions.md` | Reusable editorial decisions and unresolved questions |
| `sources/` | Original supplied files, preserved unchanged |
| `drafts/` | Individual edited chapters in Markdown |
| `assembly.json` | Canonical reviewed text, explicit order, and SHA-256 hashes |
| `edited.fb2` | Combined ebook containing completed chapters |
| `edited-review.docx` | Full text with tracked changes against the supplied translation |

Editorial reports belong in the conversation or console. They are kept out of the clean text and are not saved as report files.

## Word with Track Changes

Export paired source and edited Markdown chapters using Python 3.9+ and the standard library. List chapter identifiers explicitly in reading order:

```sh
python3 scripts/build_review_docx.py projects/omniscient-reader-side-story --chapters 553 554 555 556 557 558 559 560 561 562 563 564 565 566 --output projects/omniscient-reader-side-story/edited-review.docx
```

The document records actual OOXML insertions and deletions, including paragraph boundaries and emphasis changes, and enables tracking of further edits. In Word, use Review and All Markup to display the changes. The baseline is `sources/<id>.md`, and the result is `drafts/<id>.md`; subsequent exports show the cumulative difference from the supplied translation.

Before replacing the output, the script checks that accepting all changes recovers the edited chapters and rejecting them recovers the source. It checks text, emphasis, and paragraph styles. Empty Markdown spacing is normalized. The supported emphasis and escape syntax matches the FB2 renderer; arbitrary Markdown is unsupported. Automated checks and the macOS document importer have been run; display and accept/reject commands inside Microsoft Word have not been tested. Export requires no Word installation, API, or specific AI provider.

## Assemble reviewed chapters

From the repository root:

```sh
python3 .agents/skills/translation-edit/scripts/assemble.py init projects/my-book --title 'My book' --language en --output edited.fb2
python3 .agents/skills/translation-edit/scripts/assemble.py put projects/my-book --id '1' --order 1 --file projects/my-book/drafts/1.md --reviewed
python3 .agents/skills/translation-edit/scripts/assemble.py verify projects/my-book
```

Create and review the chapter file before running `put`. Use `--reviewed` only after editorial checks are complete. The assembler checks file consistency, hashes, chapter order, and duplicates; it does not assess translation quality or prove that every expected chapter has been supplied.

Recovery, Markdown support, and FB2 validation are described in the [assembly guide](.agents/skills/translation-edit/references/assembly.md). Back up the complete project, including `assembly.json`.

## Extract a saved source page

```sh
python3 scripts/extract_saved_chapter.py saved-chapter.html extracted-chapter.md
```

The extractor supports the RanobeLIB reader HTML structure used by the included project. It preserves paragraph boundaries and supported emphasis, does not execute HTML scripts, and requires a new output file. It is not a general website downloader or HTML converter.

## Checks

```sh
python3 -m unittest discover -s tests
python3 .agents/skills/translation-edit/scripts/assemble.py verify projects/omniscient-reader-side-story
```

The included work contains reviewed Russian chapters 553–566 of the *Omniscient Reader* side story. Its names, terms, and style references apply to that work alone.

## Using another assistant

The editing workflow is ordinary Markdown, project data uses Markdown, TSV, JSON, and FB2 XML, and executable tools use Python. Provider-specific skill discovery is optional: read the workflow manually and run the same commands. Local script checks do not establish editing quality or compatibility with every model; other assistant integrations have not been tested.
