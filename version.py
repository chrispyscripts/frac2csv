"""Single source of truth for the app version.

Keep this in step with the git tag that builds the EXE: the workflow fires on
`v*`, so tag v0.6.6 should ship VERSION = "0.6.7". The desktop app reports it
through /api/local-info and the Lab shows it beside the wordmark, so a user
can say which build they are running without opening a terminal.
"""
VERSION = "0.6.7"
