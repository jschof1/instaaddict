# Short daily sessions on macOS

`scripts/daily_growth.py` runs one automatic reviewed batch per Europe/London calendar day.
Use the existing Python environment, logged-in account and headless Android launcher.
All settings and evidence stay in the ignored `accounts/<username>/growth` directory.

The worker permits at most five follows and ten likes per day. Earlier manual bot
sessions count toward those limits. It processes at most five fresh profiles,
with at most two likes each. Comments, private messages, unfollows and publishing
are disabled. These limits bound the session; they do not guarantee account safety
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
has four minutes and the bot twenty minutes, with an overall 24-minute ceiling.
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
