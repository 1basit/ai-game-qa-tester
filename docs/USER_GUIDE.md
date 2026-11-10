# User guide — running the system and reading the results

Everything runs on your Mac from the Terminal. Commands assume you start in the project
folder:

```bash
cd ~/Desktop/FYP
```

## Step 1 — Start the three parts

The system has three parts that must all be running:

| Part | What it does | Command |
|---|---|---|
| Database (PostgreSQL) | stores accounts, projects, jobs and results | step 1a |
| Worker | analyses uploaded videos in the background, one at a time | step 1b |
| Web server | the website + API you use in the browser | step 1c |

**1a. Database** (runs in the background; the terminal stays free):

```bash
LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@18/bin/pg_ctl -D data/postgres -o "-p 5433 -k /tmp -c listen_addresses=localhost" -l data/logs/postgres.log start
```

If it says *"another server might be running"*, it is already on — fine.

**1b. Worker** — keep this Terminal tab open (it prints a line for each job):

```bash
backend/.venv/bin/gameqa worker
```

**1c. Web server** — in a **second** Terminal tab (`cd ~/Desktop/FYP` first):

```bash
backend/.venv/bin/gameqa serve --port 8000
```

When it prints `Uvicorn running on http://127.0.0.1:8000`, open **http://127.0.0.1:8000**.
If it says *"address already in use"*, a server is already running on port 8000 — just open
the address.

## Step 2 — Sign in

The demo accounts and their password:

```bash
cat data/demo-credentials.txt
```

| Account | Can do |
|---|---|
| `tester@studio.local` | upload videos, review results, export reports (in projects they belong to) |
| `lead@studio.local` | everything a tester can + create projects, add members, see cross-project statistics |
| `admin@studio.local` | everything, all projects, manage users |

Copy the password exactly (it is the long string after the email). Sessions end after
12 hours without activity — just sign in again.

## Step 3 — Projects page (home)

Shows each project with its game build, number of videos, number of detections, how many
are High / Medium / Low, and when the last analysis finished. On the right: the overall
severity summary and recent jobs. QA leads can create a project and add members here
(type the member's email under the project name → **Add**).

## Step 4 — Upload a video (3 steps)

Click **Upload & queue**:

1. choose the **project**;
2. drop a recording onto the box or click it to choose a file (`.mp4`, `.mkv`, `.avi`, up to
   2 GB — other formats are refused with a message);
3. click **Confirm upload**.

Optional settings on the right: target frame rate for the FPS check (60 or 30), sampling
rate for the vision detectors (10/12/15 FPS), and which detectors to run.

## Step 5 — Watch the job queue

The **Job queue** table (same page) refreshes every 2 seconds: status (queued →
processing → completed / completed with warnings / failed), a progress bar and the number
of detections. Analysis takes roughly **0.6× the video length** on this Mac with all
detectors (a 3-minute video ≈ 6–7 minutes). You can leave the page; it keeps running.

* **failed** → the error is shown under the status; click **Re-run** (no need to upload again).
* **completed with warnings** → results are there, but something minor went wrong (e.g. one
  detector failed); the warning is shown on the review page.

## Step 6 — Review the results

Click **Review** next to a completed job (or the file name under *Recent activity*).

**Left: the list of detections**, one row per problem found:

| Column | Meaning |
|---|---|
| Time | when it starts in the video (mm:ss) |
| Category / subtype | which of the five defect types, and the specific kind (e.g. *frozen frame*) |
| Duration | how long the problem lasted (**persistence within one occurrence**) |
| Seen | how many times **the same problem** occurs in this video (**recurrence**) — `once` or e.g. `26×` |
| Severity | HIGH / MEDIUM / LOW (colour + text) |

**Filters** above the list: click category chips and/or severity chips (they combine — e.g.
*FPS drop* + *HIGH*); **Clear filters** resets.

**Right: the evidence** for the selected row:

* the **screenshot** at the exact frame, with the affected area outlined and labelled;
* the **5–10 second clip** around it — press play;
* **Why this severity** — the rule that decided it (e.g. *"picture frozen 1.1 s ≥ 1 s (severe)"*);
* **What was seen**, **Time** (start – end, peak), **Frames**, **Recurrence**, detector, confidence.

### How to tell an issue is persistent / recurring

There are two different things:

1. **Persistent in one moment** — the **Duration** column and the *Time* line (start – end).
   A frozen picture of 1.05 s, or a flicker lasting 0.7 s. Long durations raise the severity
   (≥ 2 s; for freezes ≥ 1 s = HIGH) and the reason text says so (*"lasted 3.2 s ≥ 2 s"*).
2. **Recurring across the video** — the **Seen** column and the *Recurrence* line
   (*"Seen 4 times in this video (this is #2)"*). The same subtype in the same area of the
   screen counts as the same issue. Click **Show all N** to list only those occurrences; the
   banner's **Show all detections** returns to the full list. Recurring 3 or more times raises
   the severity one level, and the reason says *"recurs 4× ≥ 3"*.

The same information is in the exports: in JSON each detection has
`occurrence_group` and `metrics.recurrence_count`; in the PDF the severity reason mentions it.

## Step 7 — Report and export

On the review page click **Report & export**: totals per severity, a bar per category
(split by severity), and a preview of the findings. **Export JSON** (for other tools) and
**Export PDF** (for the team, with screenshots) download the report — the current filters
are applied, so you can export only e.g. the HIGH issues.

## Step 8 — Stop everything

Press **Ctrl+C** in the worker and web-server tabs, then:

```bash
/opt/homebrew/opt/postgresql@18/bin/pg_ctl -D data/postgres stop
```

## Without the website

Analyse one video directly in the Terminal (results printed, evidence saved in a folder):

```bash
backend/.venv/bin/gameqa detect path/to/video.mp4 --evidence data/cli-evidence -o data/cli-results.json
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Sign-in says *invalid email or password* | copy the password again from `data/demo-credentials.txt`; check the account exists: `backend/.venv/bin/gameqa create-user --email you@studio.local --role tester` creates one |
| Page does not open | the web server (1c) is not running |
| Errors mentioning the database / connection refused | the database (1a) is not running |
| Upload stays *queued* | the worker (1b) is not running |
| *address already in use* | that part is already running — use it or stop the old one |

## Reading the results honestly

What the detectors find on real footage is not always a real bug: the texture and animation
detectors also react to on-screen UI (menus, editor panels, HUD) and to video-editing cuts.
Use the screenshot and clip to confirm each finding. Accuracy per category is in
[EVALUATION.md](EVALUATION.md).
