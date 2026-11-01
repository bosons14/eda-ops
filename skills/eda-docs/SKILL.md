---
name: eda-docs
description: >
  This skill should be used when the user asks how to do something in OpenROAD, Yosys or OpenSTA, what
  a command, option or default does ("what does -max_fanout do", "which yosys command flattens the
  design", "how do I define a generated clock in OpenSTA"), what an error or message ID means
  (e.g. GRT-0116), or runs /eda-docs. Answers from the official documentation through the
  search_eda_docs tool, with citations.
metadata:
  version: "0.2.0"
---

# EDA documentation lookup (OpenROAD, Yosys, OpenSTA)

Flags and defaults in open-source EDA tools change between releases and are easy to misremember.
Answer from the documentation index, not from memory.

## Procedure

1. **Search.** Call `search_eda_docs` (eda-ops MCP).
   - Put exact identifiers in the query when you know them: command names (`repair_design`), options
     (`-max_fanout`), message IDs (`GRT-0116`). BM25 matches these exactly; paraphrases alone may miss.
   - Pass `tools` when the question is clearly about one tool (`["yosys"]`), to cut noise.
   - If the first results are off-target, search again with different wording: the likely command name,
     then a plain-English description of the behaviour. Two or three searches are normal; stop when
     the passages answer the question.
2. **Answer only from the passages.** Quote command names, options and values exactly as written.
   Cite each fact with the passage's URL (and section). If passages disagree, say so and cite both.
3. **When nothing answers it**, say it is not in the indexed documentation. Then offer what you
   can honestly add, clearly labelled as not from the docs (e.g. "from general knowledge, unverified").
   Never invent an option or default.
4. **Then act, if asked.** When the user wants a script or constraint written, build it from the cited
   syntax, and check it with the other eda-ops tools where possible (`review_sdc` for constraints,
   `run_sta` / `synthesize` to try it).

## If the tool reports no index

`search_eda_docs` needs an index built by eda-rag (https://github.com/bosons14/eda-rag):

```bash
git clone https://github.com/bosons14/eda-rag && cd eda-rag
pip install rank_bm25 requests numpy
python 01_ingest.py && python 02_chunk.py && python 03_index.py --chunks struct --no-dense
```

Then set `EDAOPS_DOCS_INDEX=/path/to/eda-rag` in the environment Claude Code starts from, and restart
it. Drop `--no-dense` (and set `EDAOPS_DOCS_DENSE=1`) for semantic search plus reranking. Tell the user
these steps rather than answering from memory.
