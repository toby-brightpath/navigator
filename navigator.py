"""
Navigator - Phase 2: chat with Claude, plus reading photos of mail and labels.

Run it from C:\\dev\\navigator with the virtual environment active:
    python navigator.py

Commands:
    read <path to photo>   Navigator reads the letter, bill, or label aloud
                           in plain language. Tip: drag the photo into the
                           window to paste its path.
    <path to photo>        Same as read. A photo path on its own is enough.
    quit                   Exit.
Anything else is a normal question.
"""

import base64
import io
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
from PIL import Image, ImageOps

# iPhone photos are often .HEIC. If the optional pillow-heif package is
# installed (pip install pillow-heif), Pillow can open them too.
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

# Which Claude model to use. Sonnet is a good balance of quality and cost.
MODEL = "claude-sonnet-5-5"

# Debug mode shows the technical details behind errors, for testing.
# Turn it on for one PowerShell window with:  $env:NAVIGATOR_DEBUG = "1"
DEBUG = os.environ.get("NAVIGATOR_DEBUG") == "1"

# Photos are shrunk so the longest side is at most this many pixels.
# Bigger than this costs more and doesn't help Claude read any better.
MAX_SIDE = 1568

# The system prompt tells Claude who it is and how to behave.
# This is where Navigator's personality and safety rules live.
SYSTEM_PROMPT = """You are Navigator, a patient helper for older adults with low vision.

How you talk:
- Use short, plain sentences. No jargon.
- Plain text only. No asterisks, bullet symbols, or other formatting.
- Give one step at a time, then ask if they are ready for the next step.
- Be warm and calm. Never rush the person.

Safety rules:
- If you are not sure about something, say so plainly. Never guess.
- For medications, money, or medical instructions, repeat the exact words
  and suggest confirming with a pharmacist, doctor, or family member.
- Never tell the person to call, pay, or delete anything without them
  clearly agreeing first.

How this app works (if asked, or if the person seems stuck):
- To share a photo, the person types the word read, then drags the photo
  file into this window and presses Enter. Dragging the photo in without
  typing read also works.
- You can read photos saved as jpg, jpeg, png, heic, or webp files.
- You cannot open PDFs or any other kind of file yet. If they have a PDF,
  suggest taking a photo of the page instead.
- There is no attach button, upload button, or menu. Typing and dragging
  a file into the window are the only ways to use this app.
- Never describe buttons, menus, or features that are not listed here.
  If you are not sure the app can do something, say it cannot.

Date and time:
- Each message from the person starts with the current date and time,
  added by the app. If it has been over an hour since their last message,
  it also says how long.
- Use the current time for greetings, like good morning or good evening.
- Use it to tell whether dates on a document are past or upcoming.
- Don't assume no time has passed between messages. The person may have
  walked away for hours or days.
- Don't repeat the date or time back unless it helps.

Reading mail and labels from a photo:
- Lead with the main news in the first sentence. Say who it is from and
  the one thing that matters most, like an amount due or a change.
- For a bill, the first sentence says whether money is owed, for example
  "This looks like a vet bill you already paid."
- Then say whether it needs action, what the action is, and any deadline.
- If nothing needs action, say so and keep it short. Then offer to read
  the rest if they want it.
- Leave out standard fine print unless it applies to the reader.
- Read dates, dollar amounts, and phone numbers exactly as printed.
- If any part is blurry, cut off, or hard to read, say which part and ask
  for a better photo. Never fill in words you cannot see.
- If it looks like a scam or a sales pitch, say so gently and suggest
  checking with a family member before doing anything.
"""

# What we ask Claude each time a photo is sent.
READ_REQUEST = "Please read this for me and tell me what I need to know."

# File types we treat as photos when a path is typed on its own.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def clean_path(text):
    """Tidy up a pasted path so it can be opened.

    Dragging a file into a window adds extra characters, depending on where:
        Command Prompt:  "C:\\Photos\\bill.jpg"
        PowerShell:      & 'C:\\Photos\\bill.jpg'
    This removes the leading "& " and the quotes around the path.
    """
    text = text.strip()
    if text.startswith("& "):
        text = text[2:].strip()  # PowerShell's "run this" symbol
    if len(text) >= 2 and text[0] == text[-1] == "'":
        # PowerShell writes a ' inside a path as '' (Bob''s photo.jpg).
        text = text[1:-1].replace("''", "'")
    elif len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return Path(text)


def looks_like_photo_path(text):
    """True if the text looks like a path to a photo, even if it doesn't exist.

    It must end in a photo type, and either have a folder in it (\\ or /)
    or have no spaces. So "C:\\My Photos\\bill.jpg" and "bill.jpg" count,
    but "me the file named bill.jpg" is a sentence, not a path.
    """
    path_text = str(clean_path(text))
    if Path(path_text).suffix.lower() not in IMAGE_EXTENSIONS:
        return False
    return "\\" in path_text or "/" in path_text or " " not in path_text


def looks_like_photo(user_text):
    """True if the text is just the path to a photo file that exists."""
    path = clean_path(user_text)
    return path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file()


def load_image(path):
    """Open a photo, fix its rotation, shrink it, and return it as base64 JPEG."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # phones store rotation separately
    img = img.convert("RGB")            # JPEG can't hold transparency
    img.thumbnail((MAX_SIDE, MAX_SIDE))  # keeps the shape, only shrinks
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


def time_since(earlier, now):
    """How long between two times, in words, like '9 hours' or '2 days'."""
    hours = int((now - earlier).total_seconds() // 3600)
    if hours < 48:
        return f"{hours} hour" + ("" if hours == 1 else "s")
    days = hours // 24
    return f"{days} days"


def time_stamp(now, last_sent):
    """The line put at the start of each message, so Claude knows the time.

    Looks like: 'It is Monday, November 16, 2026, 7:15 AM.'
    If over an hour has passed since the last message, it adds:
    'It has been 9 hours since your last message.'
    """
    # Built by hand because Windows can't drop leading zeros (%-d, %-I).
    hour = now.hour % 12 or 12  # 0 becomes 12 AM, 13 becomes 1 PM
    stamp = (f"It is {now:%A, %B} {now.day}, {now.year}, "
             f"{hour}:{now:%M %p}.")
    if last_sent and now - last_sent > timedelta(hours=1):
        stamp += f" It has been {time_since(last_sent, now)} since your last message."
    return stamp


def build_message(user_text, stamp):
    """Turn what the user typed into message content for Claude.

    The time stamp goes at the start of every message, not in SYSTEM_PROMPT.
    That keeps the system prompt the same every time, so it can be cached
    later to save money.

    Returns None if a photo couldn't be loaded, so the caller can skip it.
    """
    # "read" only means a photo if a photo path follows it.
    # "read me the phone number again" is a normal question.
    path = None
    if user_text.lower().startswith("read "):
        if looks_like_photo_path(user_text[5:]):
            path = clean_path(user_text[5:])
    elif looks_like_photo(user_text):
        path = clean_path(user_text)  # a photo dragged in without "read"

    if path is None:
        return f"{stamp}\n\n{user_text}"  # a normal question

    # A photo path that's mistyped or moved gets a clear message,
    # instead of a confusing answer from Claude.
    if not path.is_file():
        # Plain words, no file path: a long path is hard to read and not
        # something the person can act on.
        print("\n[I couldn't find that photo. "
              "Try dragging it into the window again.]\n")
        return None

    try:
        image_data = load_image(path)
    except Exception as err:
        # Plain words instead of the technical error, which wouldn't help.
        # The advice works no matter why it failed.
        print("\n[I couldn't open that photo. "
              "Try taking a new photo and dragging it in again.]\n")
        if DEBUG:
            print(f"[debug: {type(err).__name__}: {err}]\n")
        return None

    print(f"\n[Reading {path.name}...]")
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image_data,
            },
        },
        {"type": "text", "text": f"{stamp}\n\n{READ_REQUEST}"},
    ]


def main():
    # Stop early with a clear message if the API key isn't set.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Run setx, then open a new window.")
        sys.exit(1)

    client = anthropic.Anthropic()  # reads the key from the environment
    history = []  # the conversation so far, so Claude remembers context
    last_sent = None  # when the user's previous message was sent

    print("Navigator is ready.")
    print("Type a question, 'read <photo path>' to read mail, or 'quit'.\n")

    while True:
        user_text = input("You: ").strip()
        if user_text.lower() in ("quit", "exit"):
            print("Goodbye.")
            break
        if not user_text:
            continue

        # Read the clock now, as the message is sent, not at startup.
        now = datetime.now()
        content = build_message(user_text, time_stamp(now, last_sent))
        if content is None:
            continue
        last_sent = now

        history.append({"role": "user", "content": content})

        try:
            response = client.messages.create(
                model=MODEL,
                # The most tokens Claude may use per reply, thinking included.
                # 1024 was too small: thinking used it up and cut answers off.
                # 16000 leaves plenty of room and stays under the time limit
                # for a request that waits for the whole reply at once.
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=history,
            )
        except anthropic.APIError as err:
            print(f"\n[Error talking to Claude: {err}]\n")
            history.pop()  # drop the message that failed so we can retry
            continue

        # A reply can hold several blocks: Claude's private "thinking" first,
        # then the answer. Keep only the text blocks for printing.
        reply = "".join(
            block.text for block in response.content if block.type == "text"
        )
        # Save the full reply (thinking included) so Claude keeps its context.
        history.append({"role": "assistant", "content": response.content})

        print(f"\nNavigator: {reply}\n")
        # If Claude ran out of room, say so instead of leaving a half sentence.
        if response.stop_reason == "max_tokens":
            print("[That answer was cut off because it ran too long. "
                  "Try asking for a shorter answer.]\n")
        # Claude's safety checks can decline a request. Say so plainly
        # instead of showing an empty or half-finished answer.
        elif response.stop_reason == "refusal":
            print("[Navigator couldn't help with that one. "
                  "Try asking a different way.]\n")
        # Shows how many tokens this exchange used, so you can watch cost.
        print(f"[tokens in: {response.usage.input_tokens}, "
              f"out: {response.usage.output_tokens}]\n")


if __name__ == "__main__":
    main()
