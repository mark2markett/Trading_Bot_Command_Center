# Trading Bot Command Center

This repository is the starting point for Trading Bot Command Center.

## Project status

The repository has been initialized. Application code, a technology stack,
dependency manifests, and tests have not been added yet.

Before building the first version, define its intended workflow: monitoring
existing bots, running paper-trading simulations, or connecting to a broker.
Document the required integrations and setup commands as they are implemented.

## Development

Clone the repository and work from its root:

```sh
git clone https://github.com/mark2markett/Trading_Bot_Command_Center.git
cd Trading_Bot_Command_Center
```

In Codex cloud tasks, use the existing checkout at
`/workspace/Trading_Bot_Command_Center`. Each task already has an isolated
environment; a separate Git worktree is unnecessary unless explicitly requested.

There are currently no installation, startup, or test commands. Cloud setup can
be completed after runnable application code and its dependency manifests exist.

## Local configuration

Keep credentials out of Git. Supply API keys through secure environment settings
or ignored local configuration. Commit only example configuration without
credentials, such as `.env.example`, when application requirements are known.
