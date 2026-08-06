# Security Policy

## Reporting a vulnerability

Do not open a public issue for security problems.

Report security concerns privately using GitHub private vulnerability reporting if it is enabled for the repository. If private reporting is not enabled, contact the repository owner directly through an appropriate private channel.

## What to include

Please include:

- A clear description of the issue
- Steps to reproduce it
- Affected files, components, or versions
- Any logs, screenshots, or proof-of-concept details that are safe to share privately

## Secrets and private data

Do not commit:

- API keys
- Tokens
- Passwords
- Private URLs
- Personal addresses
- Device serial numbers
- Wi-Fi names or credentials
- `.env` files

If a secret is committed, rotate or revoke it immediately and remove it from Git history if needed.

## Supported versions

For template-generated projects, define supported versions after the project has releases.
