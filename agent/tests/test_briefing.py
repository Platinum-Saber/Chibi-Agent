import datetime as dt

from chibi_agent.briefing import (ALL_QUIET, CLOSER, MAX_WORDS, Event, Mail, Reminder, Urgency, compose,
                                  strip_codes, urgent_sentences, when)

NOW = dt.datetime(2026, 10, 31, 8, 0)  # Saturday morning
H = dt.timedelta(hours=1)


def exam(title, at, key="e"):
    return Event(key, title, at)


def test_all_quiet():
    b = compose(NOW)
    assert b.sentences == ["Report.", ALL_QUIET] and not b.items


def test_exam_reads_without_module_code():
    b = compose(NOW, events=[exam("EXAM: EN4554 Deep Learning for Vision", dt.datetime(2026, 11, 2, 9))])
    assert "Your Deep Learning for Vision exam is on Monday at 9 AM." in b.sentences
    assert "EN4554" not in b.text and b.items[0].urgency == Urgency.SOON
    assert b.sentences[0] in ("Notice.", "Report.") and b.sentences[-1] == CLOSER
    assert b.sentences[1] == "One matter requires your attention, Kryo."


def test_deadline_window_and_urgency():
    far = exam("EXAM: CS4363 Hardware Description Languages", NOW + 80 * H, "far")
    near = exam("Lab report due", NOW + 3 * H, "near")
    past = exam("Quiz 2", NOW - H, "past")
    b = compose(NOW, events=[far, near, past])
    assert [i.key for i in b.items] == ["near"]
    assert b.items[0].urgency == Urgency.NOW and "Lab report is due in 3 hours." in b.sentences


def test_events_today_and_tomorrow():
    soon = Event("a", "Project meeting", NOW + H)
    later_today = Event("b", "Gym", NOW + 9 * H)
    tomorrow = Event("c", "Dentist", NOW + 26 * H)
    gone = Event("d", "Breakfast", NOW - H)
    all_day = Event("e", "Poya day", NOW.replace(hour=0), all_day=True)
    b = compose(NOW, events=[tomorrow, later_today, gone, soon, all_day])
    assert [i.key for i in b.items] == ["a", "e", "b", "c"]  # today < soon (by time) < later
    assert "Project meeting begins at 9 AM." in b.sentences and "Poya day is today." in b.sentences


def test_mail_labels_and_names():
    mails = [Mail("m1", "Dr Perera", "EN4554 exam hall changed", "urgent", NOW - H),
             Mail("m2", "Registrar", "Fees", "bill", NOW - 2 * H),
             Mail("m3", "GitHub", "CI failed", "info", NOW),
             Mail("m4", "no-reply@daraz.lk", "Sale", "promo", NOW),
             Mail("m5", "Nimal <nimal@gmail.com>", "Group project", "reply", NOW)]
    b = compose(NOW, mails=mails)
    assert {i.key for i in b.items} == {"m1", "m2", "m5"} and set(b.mail_keys) == {"m1", "m2", "m5"}
    assert "Urgent mail from Dr Perera: exam hall changed." in b.sentences
    assert "@" not in b.text


def test_reminders_today_only():
    r = [Reminder("r1", "call the bank", NOW + 4 * H), Reminder("r2", "tomorrow thing", NOW + 30 * H)]
    b = compose(NOW, reminders=r)
    assert [i.key for i in b.items] == ["r1"] and "A reminder at 12 PM: call the bank." in b.sentences


def test_word_and_fact_limits():
    mails = [Mail(f"m{i}", f"Sender {i}", "a fairly long subject line about something important", "urgent", NOW)
             for i in range(8)]
    b = compose(NOW, mails=mails)
    assert len(b.items) == 8 and b.sentences[1] == "Eight matters require your attention, Kryo."
    facts = b.sentences[2:-1]
    assert 1 <= len(facts) <= 4 and len(b.text.split()) <= MAX_WORDS


def test_urgent_sentences():
    m = [Mail("m1", "Dr Perera", "EN4554 exam hall changed", "urgent", NOW)]
    assert urgent_sentences(m) == ["Warning.", "Urgent mail from Dr Perera: exam hall changed."]
    assert urgent_sentences([Mail("x", "a", "b", "info", NOW)]) == []


def test_helpers():
    assert strip_codes("CS4363 - Hardware Description Languages") == "Hardware Description Languages"
    assert when(dt.datetime(2026, 11, 20, 9), NOW) == "on 20 November"
    assert when(NOW + 26 * H, NOW) == "tomorrow at 10 AM"


def test_seed_picks_the_opener():
    e = [exam("Quiz 3", NOW + 5 * H)]
    assert {compose(NOW, events=e, seed=s).sentences[0] for s in range(10)} == {"Notice.", "Report."}
