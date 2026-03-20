# Glyphh Code

File-level codebase intelligence for Claude Code. Encodes every source file in
your repo as an HDC vector. Claude Code queries the index instead of scanning
files.

Same architecture as glyphh-pipedream (3,146 apps) and glyphh-bfcl (#1 on
BFCL V4). No LLM at build time. No LLM at search time. Pure HDC encoding and
cosine search.


## What it does

Compiles your codebase into a vector index. Exposes it to Claude Code via MCP.

**Without Glyphh:**
Claude reads project structure, scans likely files, reads module, reads tests.
~6,000 tokens before first useful output.

**With Glyphh:**
Claude calls `glyphh_search("auth token validation")`.
Returns: file path, confidence, top concepts, imports, related files.
Claude reads one file and acts.
~400 tokens before first useful output.

The index stores not just the vector but the token vocabulary of every file.
Search results return enough context that Claude often does not need to read
the file at all. When it does read, it already knows exactly what to look for.


## Quick start

```bash
# Deploy the code model to your runtime
glyphh model deploy glyphh-models/code/

# Compile your repo
cd your-project
python ../glyphh-models/code/compile.py . --runtime-url http://localhost:8002

# MCP tools are automatically available via the runtime's MCP server
# GET /{org_id}/code/mcp/tools → glyphh_search, glyphh_related, glyphh_stats
```

Add to Claude Code MCP config (`~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "glyphh": {
      "url": "http://localhost:8002/{org_id}/code/mcp",
      "transport": "http"
    }
  }
}
```


## Architecture

Same paradigm as all Glyphh models. The file is the exemplar.

```
Build time:  read file → tokenize path + identifiers + imports
             → encode into HDC vector → store vector + metadata in pgvector

Runtime:     NL query → encode with same pipeline
             → cosine search against index
             → return file path + top tokens + imports
             → Claude reads one file, acts
```

No LLM at build time. No LLM at runtime for search.


## Encoder

Two-layer HDC encoder at 2,000 dimensions (pgvector HNSW compatible):

| Layer | Weight | Signal |
|-------|--------|--------|
| **path** | 0.30 | File path tokens (BoW): `src/services/user_service.py` → `src services user service py` |
| **content** | 0.70 | Source file vocabulary |
| ↳ identifiers | 1.0 | All tokens from file content. camelCase/snake_case split before encoding |
| ↳ imports | 0.8 | Import/require/include targets. Strong cross-file dependency signal |

Metadata stored per file (not encoded, returned at search time):
- `top_tokens`: 20 most frequent meaningful tokens
- `imports`: list of imported module/package names
- `extension`: file type
- `file_size`: bytes


## MCP Tools

Exposed through the runtime's model-specific MCP tool system:

### glyphh_search

Find files by natural language query. Returns ranked matches with confidence
scores, top tokens, and import lists.

```json
{"tool": "glyphh_search", "arguments": {"query": "auth token validation", "top_k": 5}}
```

Confidence gate: below threshold returns ASK with candidates, never silent
wrong routing.

### glyphh_related

Find files semantically related to a given file. Use before editing to
understand blast radius.

```json
{"tool": "glyphh_related", "arguments": {"file_path": "src/services/auth.py", "top_k": 5}}
```

### glyphh_stats

Index statistics: total files, extension breakdown.


## Drift scoring

The `drift.py` module computes semantic drift between file versions:

| Drift | Label | Meaning |
|-------|-------|---------|
| 0.00–0.10 | cosmetic | Formatting, comments, rename |
| 0.10–0.30 | moderate | Logic update, new function |
| 0.30–0.60 | significant | Behavioral change, new dependency |
| 0.60–1.00 | architectural | Rewrite, interface change |


## Incremental compile

```bash
# Recompile only files changed in the last commit
python compile.py . --incremental

# Recompile files changed in a specific commit
python compile.py . --diff abc123
```

Can be wired to a git post-commit hook for automatic index updates.


## File support

Indexes: `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.java`, `.cpp`, `.c`, `.h`,
`.go`, `.rs`, `.rb`, `.cs`, `.swift`, `.sql`, `.graphql`, `.yaml`, `.json`,
`.sh`, `.css`, `.html`, `.svelte`, `.vue`, `.md`, `.proto`, `.tf`, and more.

Skips: `.git`, `node_modules`, `__pycache__`, `dist`, `build`, `vendor`,
`target`, and other build/cache directories.

Max file size: 500 KB. Binary files auto-skipped.


## Tests

```bash
cd glyphh-models/code
PYTHONPATH=../../glyphh-runtime pytest tests/ -v
```
