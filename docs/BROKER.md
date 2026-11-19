# The access broker (design note)

**Status: design only.** Nothing here is built. Build it when a project first needs it:
most likely when the agent should read production's platform logs, or when a platform
cannot scope a token to development. Until then the other layers in
[MODEL.md](MODEL.md) section 12 carry the load: scoped tokens, database roles, the gates,
runtime injection of secrets.

## The problem

Some platforms cannot scope a token finely enough.

- **Reading logs needs too much.** On Railway, a token that can read a service's logs can
  also read every variable of that environment, which means every secret. In production
  the agent should read logs and hold nothing that reads secrets, or changes anything.
- **"This environment, not that one" is not always a token scope.** Where a platform's
  token cannot be limited to the development environments, the agent would hold a
  credential that reaches production, and the wall in MODEL.md section 12 does not hold.

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

| Operation | Development | Production |
|---|---|---|
| `logs.read(service, since, filter)` | yes | yes |
| `deployments.list(service)` / `deployments.status(id)` | yes | yes |
| `service.deploy(service, environment)` | yes | no |
| `service.restart(service, environment)` | yes | no |
| `variables.set(service, environment, name)` (the value comes from the secrets manager, not from the agent) | yes | no |
| deleting a service, volume or variable | yes | never |
| deleting or transferring the project, deleting an environment | never | never |
| reading variable values | never | never |

Which environments count as production is a setting **in the broker**, changed by the
user, not something the agent sends: a write operation aimed at one answers "refused"
whatever the caller says. The production deploy stays the user's, by hand.

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
  installed when an engagement ends.

## What it does not solve

- **Database access.** Postgres already scopes natively: the agent owns the development
  database, and in production it has no role or a read-only one. No broker is needed
  there.
- **What the allowed operations can do.** In development, `service.deploy` still deploys
  whatever is on the branch. Review and the merge guard cover that.
- **A compromised broker.** It holds the powerful token, so it is kept small, has no
  inbound path except its own API, and its token is revoked with the rest of the access
  inventory when an engagement ends.

## An existing product: Infisical Agent Vault (weighed 15 Nov 2026, not adopted)

Infisical ships a credential proxy for AI agents that does most of what this note
describes. The agent holds placeholders and a session token; a proxy outside its reach
attaches the real credential to each outgoing request. HTTP services take allow-lists of
methods and path prefixes, a hook server can allow or deny a request after reading its
body, databases are reached through a local port with no password, sessions expire, and
every request is logged. Before building a broker, evaluate it first: what would be left
to write is a hook that tells one platform's GraphQL operations apart, and one access
bundle per environment.

Why it is not the default:

- **It needs the agent kept apart from the proxy.** A proxy on the agent's machine keeps
  its token where the agent can read it, and any CLI that is logged in on that machine
  goes round the proxy. In practice the agent runs in a container, or the proxy on a
  second machine. The model's default has neither (MODEL.md section 12.6).
- **It answers a less common threat.** It stops an agent from leaking or being talked out
  of a credential. A poisoned dependency or malware on the same machine is not stopped by
  it, and those are more common.
- **An allowed operation is still allowed.** In a session that may write, a manipulated
  agent can deploy or write to the database through the proxy. Scoped credentials, the
  database roles and review still carry that.
- **It was in preview**, priced by brokered request, with terms that could change.

Revisit when a project already runs its agent in a container or a cloud sandbox, when a
client requires that the agent holds no credential, or when the product has settled.

## When to build it

- **When the agent should read production's platform logs.** The alternative without a
  broker is the two log channels in MODEL.md section 12.5 (an app event table, or a log
  service with read-only tokens), which need no platform token at all.
- **When a platform cannot scope a token to development**, so the only token on offer
  would reach production.
