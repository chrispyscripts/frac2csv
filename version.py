"""Single source of truth for the app version.

Keep this in step with the git tag that builds the EXE: the workflow fires on
`v*`, so tag vX.Y.Z must ship VERSION = "X.Y.Z". The desktop app reports it
through /api/local-info and the Lab shows it beside the wordmark, so a user
can say which build they are running without opening a terminal.
"""
VERSION = "1.7.0"
