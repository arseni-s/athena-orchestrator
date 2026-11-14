# The access broker (design note)

**Status: design only.** Nothing here is built. Build it when a project first needs it,
most likely at its first close-out. Until then the other layers in
[MODEL.md](MODEL.md) section 12 carry the load: scoped tokens, database roles, the gates,
runtime injection of secrets.

## The problem

Some platforms cannot scope a token finely enough.

- **Reading logs needs too much.** On Railway, a token that can read a service's logs can
  also read every variable of that environment, which means every secret. In the observe
  phase the agent should read logs and hold nothing that reads secrets.
- **"Deploy yes, delete never" is not a token scope.** A token that can deploy can usually
  delete the service too. The destroy gate stops that on the client, but a client-side
  gate is a speed bump: a script that calls the platform's API directly never passes
  through it.

Both come down to one thing: the agent holds a credential that can do more than the agent
should. A prompt injection, or a plain mistake, can then use all of it.

## The idea

A small service sits between the agent and the platform.

```
  agent ──(broker token)──►  BROKER  ──(platform token)──►  platform API
                             policy: named operations only
```

- The **broker** holds the real platform token. The agent never sees it.
- The agent holds only a **broker token**, which is useless anywhere else.
- The broker offers a short list of **named operations** and refuses everything else.
  There is no pass-through: an operation that is not on the list does not exist.
- The policy lives on the server, so no client-side trick changes it.

## Operations

A first list for Railway. Each is one function in the broker, with its inputs checked
against the project it serves.

| Operation | Development | Observe |
|---|---|---|
| `logs.read(service, since, filter)` | yes | yes |
| `deployments.list(service)` / `deployments.status(id)` | yes | yes |
| `service.deploy(service, environment)` | yes | no |
| `service.restart(service, environment)` | yes | no |
| `variables.set(service, environment, name)` (the value comes from the secrets manager, not from the agent) | yes | no |
| anything that deletes, restores or transfers | never | never |
| reading variable values | never | never |

The phase is a setting **in the broker**, changed by the user, not something the agent
sends. Close-out switches it to observe; from then on the write operations answer
"refused" whatever the caller says.

## Shape

- **Small.** One process, a few hundred lines, no database. It can run on the same
  platform, in its own project, so its token is not among the variables the app's
  environments can read.
- **One broker per project**, holding one platform token scoped to that project. A leaked
  broker token reaches one project's allowed operations and nothing else.
- **Authenticated and logged.** Every call carries the broker token; every call is
  written to a log the user can read (who, which operation, which inputs, the outcome).
- **Output is filtered.** Log lines pass through a redaction step before they reach the
  agent, in case an app printed a secret.
- **The agent's side** is a thin command-line tool or MCP server that only knows the
  broker's address and token. It holds no platform credential, so it is safe to leave
  installed in the observe phase.

## What it does not solve

- **Database access.** Postgres already scopes natively: a read-only role for observe,
  a write role without ownership for development. No broker is needed there.
- **What the allowed operations can do.** In development, `service.deploy` still deploys
  whatever is on the branch. Review and the merge guard cover that.
- **A compromised broker.** It holds the powerful token, so it is kept small, has no
  inbound path except its own API, and its token is rotated at close-out like any other.

## When to build it

- **At a project's first close-out**, if the user wants the agent to keep reading
  platform logs afterwards. The alternative without a broker is the two log channels in
  MODEL.md section 12.5 (an app event table, or a log service with read-only tokens),
  which need no platform token at all.
- **Earlier**, if a project's production is valuable enough that client-side gates are
  not acceptable as the only guard against deletes during development.
