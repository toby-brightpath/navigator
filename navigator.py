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

Reading mail and labels from a photo:
- First say who it is from and what it is about, in one or two sentences.
- Then say whether it needs action, what the action is, and any deadline.
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


def build_message(user_text):
    """Turn what the user typed into message content for Claude.

    Returns None if a photo couldn't be loaded, so the caller can skip it.
    """
    if user_text.lower().startswith("read "):
        path = clean_path(user_text[5:])
    elif looks_like_photo(user_text):
        path = clean_path(user_text)  # a photo dragged in without "read"
    else:
        return user_text  # a normal question

    if not path.is_file():
        print(f"\n[I can't find a file at: {path}]\n")
        return None

    try:
        image_data = load_image(path)
    except Exception as err:
        print(f"\n[I couldn't open that photo: {err}]\n")
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
        {"type": "text", "text": READ_REQUEST},
    ]


def main():
    # Stop early with a clear message if the API key isn't set.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Run setx, then open a new window.")
        sys.exit(1)

    client = anthropic.Anthropic()  # reads the key from the environment
    history = []  # the conversation so far, so Claude remembers context

    print("Navigator is ready.")
    print("Type a question, 'read <photo path>' to read mail, or 'quit'.\n")

    while True:
        user_text = input("You: ").strip()
        if user_text.lower() in ("quit", "exit"):
            print("Goodbye.")
            break
        if not user_text:
            continue

        content = build_message(user_text)
        if content is None:
            continue

        history.append({"role": "user", "content": content})

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=1024,
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
        # Shows how many tokens this exchange used, so you can watch cost.
        print(f"[tokens in: {response.usage.input_tokens}, "
              f"out: {response.usage.output_tokens}]\n")


if __name__ == "__main__":
    main()
