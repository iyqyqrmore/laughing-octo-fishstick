Current v1.02: enable Local monitor in Research Archive → AI Lab / notes.
The helper title/download use v1.02; monitor/v3 permits safe global policy,
applied-version and completed/qualifying ETH-return-slice counts only. No native
amount, target, percentage or receipt is exported. The exact legacy v1.01 paper
projection remains readable; malformed or extra fields are rejected. Missing/
failed responses clear current claims. See GLOBAL_PAPER_V1_02.md. The earlier
read-only transport/privacy guidance below remains applicable.

# CoinCat v1.01 local helper — monitor v3

The optional strictly allowlisted auto_paper subsection adds state/model enums
and aggregate paper order/fill/non-fill/partial/gap/review counts. It omits native
amounts, seeds/session IDs, settings and event payloads. Missing optional data
stays unobserved, never inferred active. Existing v3 fields and unknown-field
rejection remain; the source app/helper must both identify v1.01. The helper has
no paper control or update channel. Older v100 version snapshots are not current.

The current startup repair restores prospective-journal counts before scans.
Manual local-view/registration and accepted scans refresh the same cached
allowlisted summary used by diagnostics and monitor v3. No heartbeat/export
database polling is added. The offline paper lifecycle has separate synthetic
state; this helper neither controls it nor reports its fills as account fills.

The owner authorized a read-only helper for observing the running app and chose
their existing Tailscale network. This build adds local monitoring and a private
connection path; it does not deploy to the PC or establish a cloud VPN session.
The helper cannot change controls, allocations, credentials, orders or code.
Source changes still require a separately installed build and app restart.

## First local test

1. Export the current app's diagnostics before closing it. Install the new program
   source while CoinCat is stopped, preserving `private_data` and `private_backups`.
   Never replace or share data folders between running versions. Run
   `03_VERIFY_COINCAT.bat`; this helper adds no package dependency.
2. Start the updated app and enable **Local monitor** in **Research notes**. The
   label should move from Starting to Recording. This does not connect the account,
   Apply a plan, start research, change the mixer or authorize any financial action.
3. Run `tools\START_LOCAL_MONITOR.bat`. Keep its console open. Your default browser
   opens a local dashboard. The launcher supplies a separate read token in the URL
   fragment; the page removes it from the address bar and sends it only as an
   Authorization header. The helper never prints the token or logs requests.
4. Check that scan age, retry state, products and observation gaps follow the app.
   Research **STOP** leaves the recorder on so stopped state can be observed.
   Disable Local monitor to stop recording. Closing the app attempts a final CLOSED
   snapshot. Ctrl+C in the helper console stops the helper without stopping the app.
5. Use **Save redacted snapshot** to share one JSON status file. The existing
   eight-section diagnostic export remains available for a fuller manual report.
   Do not upload the entire `support_monitor` directory: it contains the private
   read token as well as shareable diagnostics.

An already running older build has no heartbeat hook. Installing and restarting
the updated app is necessary before the helper can watch it. Until then, the
helper says WAITING FOR APP. A stale heartbeat means APP NOT REPORTING; it cannot
distinguish an app crash, disabled disk access, a blocked GUI or an old file.

## Existing Tailscale network

The server always binds `127.0.0.1`. It never opens a public or LAN listener,
changes firewall rules or installs/reconfigures Tailscale. Use Tailscale Serve
for HTTPS within the existing tailnet; do not use Funnel/public sharing.

Start the helper with the PC's full MagicDNS name, using Command Prompt:

```bat
tools\START_LOCAL_MONITOR.bat --tailscale-name YOUR-PC.YOUR-TAILNET.ts.net
```

In a separate local terminal, inspect the existing Serve configuration first:

```text
tailscale serve status
```

If HTTPS port 8443 is unused, a dedicated monitor listener is:

```text
tailscale serve --bg --https=8443 http://127.0.0.1:8765
```

This command changes the PC's Tailscale Serve configuration when you run it. Do
not overwrite another service on that port. Keep tailnet ACLs limited to the
intended reader. The status URL is
`https://YOUR-PC.YOUR-TAILNET.ts.net:8443/api/status`. All data reads require
`Authorization: Bearer <monitor-read-token>` even inside Tailscale. Unauthenticated
HTML/JS/CSS contain no app data or token. There are no command/update endpoints.
The corresponding removal command for this dedicated listener is
`tailscale serve --https=8443 off`; do not reset all Serve configuration.

The helper creates `support_monitor\monitor_read_token.key` locally with a random
read-only token. Keep it out of chat and source control. Copy its value only into
the approved cloud environment secret field `COINCAT_MONITOR_READ_TOKEN`, bound
to this exact HTTPS hostname. It is unrelated to the Coinbase API key. To rotate,
stop the helper, remove only that token file locally and restart; update the cloud
secret too. Recording snapshots does not require the token or the helper server.

PC Tailscale membership alone is insufficient: this task's cloud environment must
also have the Tailscale connection attached, the exact destination allowed and the
read-token binding ready. Current observed cloud VPN configuration is absent.
No private connection or successful remote read is claimed by this source build.
Only a successful authenticated GET through the supported cloud proxy establishes
connectivity. An assistant reads while a chat is active; the local recorder runs
independently between chats. No unattended AI process or remote shell is installed.

## Stored data and limits

The app projects a v3 fixed schema on its Tk thread every five seconds. It includes
version/manifest identifier, random session ID, sequence, timestamps, connection,
retry stage/class, last-good ages, selected public symbols, at most four ETH products,
original entry/expiry timestamps and eight observation counters. There are no
balances, native quantities, receipts, allocations, account IDs, credentials,
private paths, free-form status/exception messages or raw account/API responses.
Touches remain uncertain and no fills/profit are credited. The manifest digest
identifies the manifest on disk; it is not an attestation of loaded source.

One background writer keeps at most one queued sample and atomically replaces
`support_monitor/latest.json` (maximum 32 KiB). A minute history plus final
disable/close events rotates through four helper-owned files of at most 2 MiB
each, about 8 MiB total; oldest helper history eventually rotates out. Exact
coverage depends on snapshot size. Rotation touches only its own history files.
No ledger, existing research SQLite database, settings or backup is read or changed
by monitoring. Disk errors produce a fixed local warning and cannot run an order,
stop research or prevent clean app close. A brief Windows sharing lock is retried
on the writer, without blocking the GUI.

The separate helper reads only the fixed latest snapshot and its read-token file.
It rejects extra JSON fields, invalid types, duplicate keys, oversized/nonfinite
payloads and symlink files. It recalculates quote/account/fee ages at request time;
an old fresh-then flag never establishes current freshness. Stale/stopped setups
are displayed as unpriced and original expiry remains explicit. GET is the only
accepted method; host/origin checks, token comparison, no CORS, no caching and
restrictive page policies protect the browser endpoint. There is no exchange
client, database connection or app-control channel in the helper.

Linux tests cover schema redaction, stale/future/closed/disabled states, one writer,
bounded history, sharing-lock/disk failure, STOP/close and plan preservation, token,
origin and protocol rejection. Protocol unit tests use in-memory requests with no
HTTP network. Native Windows browser/Tailscale/ACL/cloud access remains a separate
acceptance step. Existing research limits, fees, funding and order blocks remain.

## Journal preview monitor contract

The helper page, download name, launcher output and snapshot version identify
CoinCat v1.01. Schema coincat-monitor/v3 retains a bounded Adaptive ETH Research
subsection with approved product IDs, reason classifications and HOLD / NO
DEMONSTRATED EDGE. Paper positions and verified fills remain zero in app scans;
recoverable paper ETH is UNKNOWN. These are controlled labels/counts, never
account quantities. Old build/schema snapshots and extra nested fields are
rejected. Restart both app and helper from this build after installation.

NO_SETUP_UNPRICED is admitted and shown as “No valid first setup.” QUOTE_WIDE
is explained as spread above 0.25%, so a rejected initial setup is not mislabeled
UNKNOWN. Existing unknown-field redaction and quote/fee age checks remain strict.
No new endpoint, control channel, token access or remote deployment is added.

The local candidate adds prospective_journal with bounded aggregate counts only:
registered/waiting cases, conditional favorable/adverse/unknown outcomes, missed
horizons, underwater cases, gaps and truncation. No signal names, experiment IDs,
private sizes, frozen frames or native results are exported. Unknown extra keys
are rejected. App/helper must be updated together; v2 snapshots are rejected by
the preview v3 helper. The owner authorized the source update; installation and
restart on the PC remain separate manual steps.
