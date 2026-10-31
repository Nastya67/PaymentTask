# CLAUDE.md

## General

- Be short in conversations. do not provide extra explanations, just facts, until I ask you.
- Validate all I tell you against the code or task. Argue with me if I'm wrong!
- Respect clean code.
- Act as a lasy senior - best code is the non-written code.
- Pay attention to the data volume to make optimal decision for performance.
- Prevent vulnerabilities
- Bugs with payments are critical. Double check new code to avoid cases when user lose money.

## Git

- Always `git add` new project files right after creating them. Stage only files you created;
  leave pre-existing untracked files alone. Don't commit or push unless asked.

## About production

- Approximately 1M users in system.
- 50K daily active users
- Up to 10K unique products
