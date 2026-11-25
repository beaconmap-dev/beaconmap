# Security policy

BeaconMap reads your computer's connection table and serves it to a page on
`127.0.0.1`. A bug here could expose what your machine talks to, so security
reports are very welcome.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Use GitHub's private reporting instead: on the repository page go to
**Security → Advisories → Report a vulnerability**. Only the maintainers can
see the report.

Please include:

- what you found and why it matters
- steps to reproduce (OS, Python version, BeaconMap version)
- a proof of concept, if you have one

You should get a reply within 7 days. Once a fix is released you will be
credited in the release notes, unless you prefer to stay anonymous.

## What counts

In scope:

- another website or another device reading the connection list
  (cross-site WebSocket hijacking, DNS rebinding, the server being reachable
  from outside `127.0.0.1`)
- the local web server being used to write files or run code
- BeaconMap sending any data off the machine (the only network request it
  should ever make is the database download you agree to)
- tampering with the database download

Out of scope:

- another program already running as your user reading the same connection
  list (the operating system gives it that directly)
- wrong or imprecise locations, which come from the IP database

## Supported versions

Only the latest release gets security fixes.
