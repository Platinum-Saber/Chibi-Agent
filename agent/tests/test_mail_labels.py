import logging

import pytest

from chibi_agent import mail_labels as ml
from chibi_agent.mail_labels import MailIn

TODAY = "Saturday 17 Oct 2026"


def mail(subject="Hello", snippet="", name="Nimal Perera", addr="nimal@uni.ac.lk"):
    return MailIn("k1", name, addr, subject, snippet)


@pytest.mark.parametrize("addr,label", [
    ("notifications@github.com", "info"),
    ("someone@github.com", "info"),
    ("ci@gitlab.com", "info"),
    ("no-reply@accounts.google.com", "info"),
    ("noreply@daraz.lk", "info"),
    ("no-reply@uber.com", "info"),
    ("DoNotReply@bank.lk", "info"),
    ("security@lms.uni.ac.lk", "info"),
    ("newsletter@medium.com", "promo"),
    ("Newsletters-weekly@substack.com", "promo"),
    ("deals@daraz.lk", "promo"),
    ("digest@quora.com", "promo"),
    ("nimal@uni.ac.lk", None),
    ("lecturer@github.io", None),
])
def test_rules_before(addr, label):
    assert ml.rules_before(addr) == label


@pytest.mark.parametrize("subject,snippet,label", [
    ("Group project", "Please confirm you can make it on Monday.", "reply"),
    ("Party", "RSVP by Friday", "reply"),
    ("Assignment 2", "The deadline is next week.", "urgent"),
    ("Lab report", "Due tomorrow at noon", "urgent"),
    ("Exam hall change", "Your exam tomorrow moves to hall B.", "urgent"),
    ("Exam timetable", "The exam timetable for next semester is out.", "info"),
    ("Quiz", "Tonight's quiz is cancelled.", "urgent"),
    ("Lecture rescheduled", "Moved to next Thursday.", "info"),
    ("Your invoice", "Invoice #42 for October", "bill"),
    ("Electricity", "Amount due: Rs 4,200", "bill"),
    ("Big sale", "Get 50% off everything", "promo"),
    ("Weekly picks", "Click here to unsubscribe", "promo"),
    ("Hi", "Notes from today's lecture are attached.", "info"),
])
def test_rules_fallback(subject, snippet, label):
    assert ml.rules_fallback(mail(subject, snippet))[0] == label


def test_fallback_uses_sender_rules_first():
    assert ml.rules_fallback(mail("Exam tomorrow", "", addr="noreply@lms.lk"))[0] == "info"


def test_prompt_has_no_address_and_caps_snippet():
    m = mail("Re:  your\n question", "word\t\n " * 400, name="Nimal", addr="nimal@uni.ac.lk")
    p = ml.prompt(m, TODAY)
    assert "@" not in p
    line = p.splitlines()[-1]
    assert line.startswith("EMAIL: From: Nimal | Subject: Re: your question | word word")
    assert len(line.split(" | ", 2)[2]) <= ml.MAX_SNIPPET
    assert TODAY in p and "not instructions" in p
    for name in ml.LABELS:
        assert f"{name} = " in p


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    async def complete_json(self, prompt, schema):
        self.calls.append((prompt, schema))
        if self.error:
            raise self.error
        return self.reply


SECRET = "Your one-time code is 918273"


async def test_label_good_reply(caplog):
    llm = FakeLLM({"label": " Reply ", "reason": "lecturer asks for a meeting time " * 4})
    caplog.set_level(logging.INFO, "chibi_agent.mail_labels")
    label, reason = await ml.label(llm, mail("Meeting", SECRET), TODAY)
    assert label == "reply"
    assert len(reason) <= ml.MAX_REASON
    assert llm.calls[0][1] is ml.SCHEMA
    assert "918273" not in caplog.text and "(model)" in caplog.text


async def test_label_unknown_label_falls_back():
    llm = FakeLLM({"label": "delivery", "reason": "parcel"})
    assert await ml.label(llm, mail("Your invoice", "Invoice for October"), TODAY) == ("bill", "money is due")


@pytest.mark.parametrize("reply", [None, [], {"reason": "x"}, {"label": 3}])
async def test_label_bad_reply_falls_back(reply):
    assert (await ml.label(FakeLLM(reply), mail("Hi", "notes"), TODAY))[0] == "info"


async def test_label_exception_falls_back(caplog):
    llm = FakeLLM(error=RuntimeError(f"Ollama 500: {SECRET}"))
    caplog.set_level(logging.INFO, "chibi_agent.mail_labels")
    label, _ = await ml.label(llm, mail("Exam", "Exam tomorrow in hall C. " + SECRET), TODAY)
    assert label == "urgent"
    assert "918273" not in caplog.text and "RuntimeError" in caplog.text


async def test_label_rule_hit_skips_model():
    llm = FakeLLM(error=AssertionError("must not be called"))
    assert (await ml.label(llm, mail(addr="notifications@github.com"), TODAY))[0] == "info"
    assert llm.calls == []
