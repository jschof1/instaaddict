# Short daily sessions on macOS

`scripts/daily_growth.py` runs one automatic reviewed batch per Europe/London calendar day.
Use the existing Python environment, logged-in account and headless Android launcher.
All settings and evidence stay in the ignored `accounts/<username>/growth` directory.

The worker permits at most five follows and ten likes per day. Earlier manual bot
sessions count toward those limits. It processes at most five fresh profiles,
with at most two likes each. The bot's comments, private messages, unfollows and
publishing remain disabled. A separate optional helper can post at most two
prepared public comments as `uk.tradeleads` per UK day. These limits bound the session; they do not guarantee account safety
or follower growth. Instagram restrictions stop the worker for review.

## Private setup

Create `settings.json` containing:

```json
{"dailyFollows": 5, "dailyLikes": 10, "timezone": "Europe/London"}
```

`queue.json` contains `preparedAt` and `targets`. Each target needs `handle`,
`sourceUrl`, `instagramUrl`, `trade`, `serviceArea` and `evidence`. The source must
be the business's own site or business listing explicitly linking its Instagram
account. Use lowercase handles without `@`, and canonical Instagram URLs starting
`https://www.instagram.com/`. Review relevance before adding targets. Queue data
is not committed. Previously interacted or attempted profiles are never replayed
automatically. Refill this finite queue when the status shows it is empty.

The existing `~/Applications/InstaAddict/Start Android.command` must start the
configured AVD on port 5554 in the foreground. The worker starts it only when
`emulator-5554` is absent and shuts down only that owned session. It does not
take over an already open emulator. Keep the original account filters with
comment/PM permissions disabled.

### Optional finite public comment queue

There is no AI generation, discovery or generic fallback. The parent prepares each
comment from live profile and caption proof. `sourceUrl` must be the matching
Instagram profile; retain any business website research separately. Only
`uk.tradeleads` is supported. Private messages stay at zero. The scoped public
comment permission does not add a per-draft approval step.

Absent `comment-policy.json` means off. To enable it, create these private files
in `growth` (mode 600), including an initially empty ledger if there is no history:

`comment-policy.json`:

```json
{"enabled":true,"dailyLimit":2,"timezone":"Europe/London"}
```

`comment-queue.json`:

```json
{"comments":[{"id":"roof-20261019-1","handle":"example.roofing","postUrl":"https://www.instagram.com/p/CODE/","captionSnippet":"Exact excerpt from this post","text":"Prepared post-specific comment.","sourceUrl":"https://www.instagram.com/example.roofing/","expiresAt":"2026-10-26T17:00:00+00:00"}]}
```

`comment-ledger.json`:

```json
{"version":1,"intents":[]}
```

Queue fields are required. IDs use letters, digits, hyphens or underscores. URLs
must be exact HTTPS `instagram.com` or `www.instagram.com` post URLs, either
`/p/CODE/` or `/handle/p/CODE/`, without query strings or fragments. Any URL handle
must match `handle`. Caption excerpts and comments must be nonempty and at most
220 characters. Reject links and sales pitches; validation includes a conservative
content filter, while relevance and wording come from the prepared source proof.
Use timezone-aware ISO timestamps and normally a seven-day expiry. Expired entries
are skipped; malformed entries stop the run even if expired. Refill the finite
queue as needed. Status reports enabled, daily charged, remaining and pending
(unexpired, unconsumed) counts.

Each ledger intent copies all seven queue fields and adds `day` (UK date),
`reservedAt` (aware ISO timestamp) and `state`. Optional fields are `finishedAt`,
`evidence` (private XML path), and `receiptSessionId` when the same confirmed
comment is already counted in a bot session. Import earlier manual comments as
`posted` intents with their actual timestamps before enabling the helper. For example:

```json
{"version":1,"intents":[{"id":"manual-20261019-1","handle":"example.roofing","postUrl":"https://www.instagram.com/p/CODE/","captionSnippet":"Exact excerpt from this post","text":"Exact full comment already posted.","sourceUrl":"https://www.instagram.com/example.roofing/","expiresAt":"2026-10-26T17:00:00+00:00","day":"2026-10-19","reservedAt":"2026-10-19T12:00:00+01:00","state":"posted"}]}
```

The durable states are `reserved` → `posted` or `alreadyPosted`. Every other
outcome after reservation becomes `uncertain` and requires fault review. The
reservation is atomically replaced and both the file and directory are fsynced
before UI work. Power loss can leave `reserved`; recovery changes it to
`uncertain`. Every state charges the reservation's UK day. Historical bot
`total_comments` also charge that day; `receiptSessionId` avoids counting the
same confirmed receipt twice. Unknown/manual actions outside these records must
be reconciled into the ledger. Never reset the ledger to regain budget.

An attempted post shortcode OR normalized full comment text is permanently
consumed across days. An uncertain intent is never retried. A safety fault or
unresolved reservation blocks further actions until reviewed. Even a known
pre-submit failure conservatively consumes its intent.

For each intent the helper verifies the logged-in account, exact post owner and
caption excerpt, empty known composer and absence of reply context or restrictions.
It verifies the exact typed text, clicks Post once and requires a single XML node
whose complete description is `uk.tradeleads said FULLCOMMENT`. It then reopens
the exact post, revalidates owner/caption and saves a fresh full receipt. Missing
or ambiguous confirmation stays uncertain. An already visible exact comment is
charged as `alreadyPosted` without typing. XML evidence is private in
`growth/comments-log` (folder 700, files 600).

The bot's saved job must be new, match this config, finish successfully with
zero recoveries/crashes and zero unexpected actions before comments can start.
The helper runs under `.venv/bin/python` in the same owned emulator session.
When the follow queue is empty or its budget used, eligible prepared comments
can run alone. There is no additional schedule. A started day still prevents
another same-day run.

For read-only selector checks, import `scripts/public_comments.py`, import
`InstaAddict.core.device_facade` before connecting uiautomator2, then use
`CommentUI(device, growth_path).open_and_validate(entry)`. This path only opens
the account/post/composer and saves XML: it does not type, submit or change the
ledger. It dismisses an observed previous comments sheet with one Back, and uses
one further Back only for an observed post detail without the profile tab.

```sh
.venv/bin/python scripts/daily_growth.py status --account uk.tradeleads
.venv/bin/python scripts/daily_growth.py run --account uk.tradeleads
.venv/bin/python scripts/daily_growth.py pause --account uk.tradeleads
.venv/bin/python scripts/daily_growth.py resume --account uk.tradeleads
```

## Schedule and operating limits

Use a per-user LaunchAgent with `StartCalendarInterval` hour 10, minute 0, with
the Mac's time zone set to Europe/London. Set absolute Python/script paths,
`WorkingDirectory` to the checkout, `RunAtLoad` false and `KeepAlive` false.
Enable the schedule only after a complete supervised session succeeds.

The Mac mini must remain powered and its user logged in. A sleeping Mac runs
the missed calendar job when it wakes; a powered-off Mac cannot run it. The
worker prevents sleep only during a session. The laptop and chat can be closed.

Starting Android requires 8 GiB free; a run stops below a 3 GiB reserve. Boot
has four minutes and the bot twenty minutes. The comment helper has at most
180 seconds, sharing the overall 24-minute ceiling. Pause, UK day rollover,
emulator loss, log size and the disk reserve are monitored during comments too.
Overlapping workers, another bot, an occupied emulator, duplicate days and
unreviewed faults prevent new actions. A started day is never retried
automatically, even when it performed no actions.

`state.json` and `days/YYYY-MM-DD.json` retain results; `logs` retains diagnostics.
Bot-recorded likes/follows are outgoing actions, not proof of new followers or
leads. A clean exit must also have a saved, completed job without crashes or
watchdog recoveries before the worker reports success.

Pause stops an active bot and its owned emulator. Resume removes only a manual
pause; it cannot clear `fault.json`. Investigate the saved log, reconcile any
uncertain actions and repair the cause before manually archiving a safety fault.
An unfinished journal after a power loss also requires review. Do not delete
journals or reset session counters to force another same-day run. During setup,
a developer may make a deliberate validation run after repairing a fault: preserve
the previous journal under an attempt filename in `days`, archive the fault with
the repair evidence, and reconcile all confirmed actions before another run.
The scheduler never performs this recovery. Recorded `Followed @...` transitions
are charged even if interruption preceded the bot's per-profile counter update.
