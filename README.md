# Navigator

A patient, plain-spoken helper for older adults with low vision, built on Claude.

Navigator reads photos of mail, bills, cards and labels, and tells the person what they need to know: who it's from, whether anything needs doing, and by when. It answers one step at a time, in short sentences. It never guesses at words it can't see.

It's the first tool from [BrightPath Vision](https://brightpath.vision), which helps low-vision older adults use technology to stay independent. The first real tester is my mom.

---

## What it sounds like

```
You: [drags in a photo of a bill]

Navigator: This is a bill from your gas company. You owe $64.20, and it is
due December 3.

You can pay it by mail or by phone. Would you like me to read you the
phone number?

You: yes

Navigator: The number is (555) 014-2290.

Said slowly: five, five, five. Then zero, one, four. Then two, two, nine, zero.

Would you like me to say it one more time?
```

*(Sample with made-up details. Real test documents stay private.)*

---

## Design principles

- **Lead with the news.** The first sentence says who it's from and the one thing that matters, like an amount due or a decision.
- **One step at a time.** Short answers, then an offer to go on. If nothing needs doing, say so and stop.
- **Never guess.** If part of a photo is blurry, cut off or covered by glare, Navigator says which part and asks for a better photo.
- **Read numbers exactly.** Dates, amounts and phone numbers are read as printed, and phone numbers are read back in small groups of digits.
- **Know what time it is.** Every message carries the current date, time, and how long it's been since the last one. Older adults often leave apps open for days. Navigator says "good morning" in the morning, and knows a 2021 reminder is long past.
- **Plain errors.** If a photo can't be found or opened, the person sees one plain sentence, not a stack trace.
- **Safety first.** For money, medicine or legal letters, Navigator quotes the exact words and suggests checking with a family member, pharmacist or the sender. It never tells someone to call, pay or delete anything without them agreeing first.

---

## How it was built

- **Python 3.13** and the **Anthropic Python SDK**, using Claude Sonnet with image input
- **Pillow** (plus pillow-heif for iPhone photos) to fix rotation and shrink photos before sending
- Built with **Claude Code** in VS Code, in a review-first loop: Claude Code proposes a change, I read the diff, test it on real documents, then commit

### Testing on real documents

Each change is tested on real mail photos before it's committed, using the same photo before and after so the difference is clear. A few things that testing caught:

| Found | Fix |
|---|---|
| Answers stopped mid-word on a complex invoice | `max_tokens` was too small once thinking was counted; raised it, and Navigator now says plainly if an answer is ever cut off or declined instead of failing silently |
| Called 2021 vet reminders "future visits" | Added the current date and time to every message, read from the clock when it's sent, not at startup |
| "Read me the phone number again" was treated as a file path | Only treat `read <text>` as a photo when the text is a real image file |
| Main news buried in the 2nd paragraph | System prompt rule: lead with the main news in the first sentence |

`tests/fake_gap.py` checks the time-awareness behavior, like being away overnight, without waiting hours for real time to pass:

```
python tests/fake_gap.py              # 9-hour gap ending now
python tests/fake_gap.py --overnight  # 10:15 PM to 7:15 AM
```

---

## Run it yourself

Requires Python 3.13+ and an [Anthropic API key](https://console.anthropic.com).

```y
git clone https://github.com/toby-brightpath/navigator.git
cd navigator
python -m venv .venv
.venv\Scripts\activate          # Windows (macOS/Linux: source .venv/bin/activate)
python -m pip install -r requirements.txt
```

Set your API key as an environment variable named `ANTHROPIC_API_KEY`, then:

```
python navigator.py
```

Type a question, or drag a photo of a letter into the window and press Enter. Type `quit` to exit.

Set `NAVIGATOR_DEBUG=1` to see the technical details when a photo fails to open.

---

## What's next

- Keep long-running conversations from growing without limit (summarize older turns, don't resend old photos)
- Reminders, using Claude tool use ("remind me to pay this on the 1st")
- PDF support
- A phone-friendly version

---

*Built by Toby Mills · [BrightPath Vision](https://brightpath.vision)*
