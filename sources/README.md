# sources

This directory is reserved for source adapters.

Each source should ideally expose a clear interface for:

- fetching latest items
- normalizing fields
- deduplicating records
- reporting failures

Candidate source folders:

- `x/`
- `wechat/`
- `arxiv/`
