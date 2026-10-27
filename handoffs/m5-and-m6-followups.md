# Handoff: M5 (personal info) and M6 follow-ups

**Goal:** finish v1 by adding M5 (Google Calendar + Gmail read-only, Windows notifications, a briefing) and closing the M6 loose ends.

## Decisions
- Python, four processes (agent / overlay / voice / Ollama) on a loopback WebSocket. Protocol v2 is in `shared/chibi_shared/protocol.py`; bump VERSION on any shape change.
- Raphael is an agentic desktop companion. She addresses the user as "Kryo", or "Sir" when it's serious; never "Master". Persona stays under 3 k characters (tool list is generated from the registry).
- **Voice:** F5 clone `ref_06_clean.wav`, NFE 8, speed 0.90, "!" calmed to ".". Personal use only; clips never go in git.
- **Side-effect tools ask for confirmation** (HUD Yes/No, or a spoken yes/no). Exceptions: media, volume, remember, set/cancel_reminder.
- **Tool failures are flagged to the model** ("THE TOOL FAILED…"). A claimed action with no tool call gets one nudge.
- **Untrusted text is data:** screen, file, web and mail content is wrapped as data. Memory extraction only reads Kryo's words and her replies.
- **Gaming mode:** a fullscreen app or the tray toggle unloads the LLM and voice models; push-to-talk reloads them if NVML reports 4.8 GB free.
- **M5 rules** (from `docs/scope.md`):
  - Google OAuth is read-only. **Kryo creates the Google Cloud OAuth client and signs in themselves**; never automate the sign-in.
  - The refresh token goes in Windows Credential Manager (`keyring`).
  - Mail is polled every 5 min.
  - The briefing composer is code (urgency rules, 72 h deadline window, names not addresses, "Notice. … End of report."). The LLM only labels single mails.

## Files
- `docs/{scope,architecture,character,spikes}.md`, `CLAUDE.md`: what v1 is, design, persona/voice, measurements, rules and commands.
- `agent/chibi_agent/orchestrator.py`: turn loop, tool loop, announce (use it for briefings).
- `agent/chibi_agent/tools/`: registry (`__init__.py`, `CTX` for stateful services), `runner.py` (gate, audit), one module per tool group. Add `calendar.py`, `gmail.py` and `briefing.py` here.
- `agent/chibi_agent/schedulers.py`: reminder scheduler; extend it for mail polling and the morning briefing.
- `agent/chibi_agent/memory/`, `vram.py`, `control.py`: memory store/recall, gaming mode, tray commands.
- `overlay/chibi_overlay/` (stage, window, hud, tray, env) and `voice/chibi_voice/` (STT/TTS; `clips.py` = fixed lines).
- Saber-Theme `BriefingComposer` (read-only reference): `D:\Projects\Mobile Applications\Saber-Theme`, see its `docs/architecture.md` → Briefing.

## State (branch `v1`, last commit d92aaff; not pushed)
- **Works and tested** (50 agent / 74 overlay / 30 shared / 18 voice tests pass): voice turns (first audio 1.1–1.6 s), 26 tools (live replay 20/21), memory and reminders, two forms with transform/HUD, multi-monitor following, gaming mode (6.2 GB → 1.2 GB in 0.3 s), single-instance lock, child cleanup via job object.
- **Untested by hand:**
  - the tray menu (every item, including memory viewer, settings and Start with Windows);
  - drag/throw onto a title bar and onto monitor 2 with the real mouse.
- **Closed after d92aaff :**
  - the overlay caps at 30 fps on battery (`env.on_battery`, polled every 10 s);
  - danger reports (burning, smoke, sparks, gas, …: `orchestrator.URGENT`) open with "Warning." from code, and the model's own opener is dropped;
  - gaming mode reloads the LLM and F5 at PTT down, while Kryo speaks (`VramManager.on_ptt`); the new latency is not measured yet;
  - stale "Master" lines in `docs/architecture.md`;
  - Quit unloads her model from Ollama (Ollama itself is the Ollama app's server and stays).
- **Tray tested by Kryo (2026-10-17):** works. Start with Windows makes the Startup-folder shortcut; Task Manager lists it as "pythonw".
- **Known gaps:**
  - battery-saver state (Kokoro on CPU under 30 %) not built, as planned for v1;
  - Spotify can't play a named playlist (needs the Web API in M5, Premium for playback);
  - `test_cases_live.py` can't find `qwen3.5:4b` when run from the Claude app (Ollama there doesn't see the models in `D:\Projects\Chibi-Agent-Project\ChibiAgent\ollama`).
- **Testing gotcha:** processes started from the Claude app get MSIX-virtualized AppData, and their hotkey hook also catches Kryo's Alt+1. Never run a test instance while Kryo's is running.

## M5 progress
- **Part 1 done:** `google_auth.py` with several accounts (InstalledAppFlow with the account chooser in Kryo's browser; email from `calendars/primary`; keyring `google:<email>` + `google:accounts`; `invalid_grant` drops only that account), the tray's Google accounts submenu (protocol v3, `State.google_accounts`, `google_signout` arg = email or empty for all), and the read-only `calendar_events` tool (`tools/calendar.py`: code-built ranges and lines, every account's selected calendars merged, dedupe by `iCalUID`, per-account error lines, untrusted). 73 agent tests pass.
- **Accounts to connect:** sansikasuhan5@gmail.com, sansikawaduge@gmail.com, sansika.22@cse.mrt.ac.lk. The university one is Workspace: its admin may block unverified apps or Gmail scopes ("Access blocked"); only the university can lift that.
- **Kryo's setup:** Google Cloud project "Chibi-Agent", Calendar + Gmail APIs, External app in **Testing** with the three accounts as test users, Desktop client JSON at `%APPDATA%\ChibiAgent\google_client.json`. Testing means a 7-day sign-in expiry. Production needs a public home page and privacy-policy URL (Branding), so it is deferred; a GitHub Pages site would do.
- **Verified by Kryo (2026-10-17):** all three accounts signed in (the university one too); "exams on November 2nd and 3rd" found both from `sansikasuhan5`. Fetches now run accounts and calendars in parallel over one client (was ~10 s per call; not re-timed live yet).
- **Ollama gotcha:** the Ollama tray app's server (started at login) uses the default model folder; Kryo set user env `OLLAMA_MODELS=D:\Projects\Chibi-Agent-Project\ChibiAgent\ollama`. The agent now logs missing models at startup and says "Ollama cannot find my model" on that failure. Snipping Tool no longer triggers gaming mode.
- **Part 2 done (d463cf7):** `tools/gmail.py`: `mail_list` (default: unread inbox, no promotions/social/updates/forums, last 3 days; `about` = Gmail search over 30 days; numbered, newest first, sender names only, Gmail's IMPORTANT label shown) and `read_mail` (by number from the last list; plain text preferred, HTML stripped, quotes dropped, 1,500 chars, attachment names). Shared helper `tools/_google.py`. Untrusted tool results are logged as a length only. Tried on Kryo's real mail: works (list ~4 s, search ~2.5 s, read 0.5-2 s).
- **Watch:** the real prompt is 2,953 / 3,000 characters (a test now checks it). Part 3 tools must replace or shorten existing descriptions.
- **Part 3 done:** `mail_labels.py` (written in a side session), `briefing.py`, `mailwatch.py`, `mail`/`kv` tables in the store, `orchestrator.report()` and the "briefing" command, `[briefing]` config. Automated senders are named by domain ("github"). Tested live by Kryo (2026-10-17): morning briefing once a day, "briefing" on demand, an urgent test mail announced. 147 agent tests pass. Fixes from the test: the "thinking" mood is sent before PTT-up (an instant empty transcript left her stuck thinking); mail labelling waits while Kryo is talking and the first poll runs 90 s after start (Ollama serves one request at a time); voice.log transcript lines now carry peak/rms and the mic name (the empty transcripts were a faulty headset mic). Still worth watching: labels on university/Moodle notices (the prompt's promo line includes "automated notices").
- **Left for later:** Windows notifications (WinRT listener permission), Moodle deadlines, the thought cloud, Spotify Web API.

## Next step
Ask Kryo to try the tray (`python chibi.py`, then right-click the "R" tray icon) and report back. Then plan M5 in plan mode, starting with the Calendar tool and the OAuth flow, and give Kryo exact Google Cloud console steps to create a Desktop OAuth client.
