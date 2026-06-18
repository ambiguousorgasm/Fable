# MCP Setup Notes

No live MCP servers are configured by default. The root `.mcp.json` intentionally contains an empty `mcpServers` object.

Add project-scoped MCP servers only when you know the real tools needed for the workflow.

Examples of useful future MCP integrations:

- GitHub MCP for issues, pull requests, and repository search.
- Database/SQLite MCP for inspecting event logs and world-state stores.
- Browser/devtools MCP for debugging the React interface.
- Filesystem MCP only when Claude Code needs access outside the project root.

Keep secrets in environment variables or local configuration. Do not commit API keys or private tokens.
