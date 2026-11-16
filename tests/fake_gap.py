"""Send Navigator a message as if the user had been away for 9 hours.

Makes one real call to Claude (a fraction of a cent), so it needs
ANTHROPIC_API_KEY set, the same as navigator.py.

Usage, from C:\\dev\\navigator:
    python tests\\fake_gap.py              The real time now, last message 9 hours ago.
    python tests\\fake_gap.py --overnight  Pretend it's 7:15 AM and the last
                                          message was 10:15 PM the night before.
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# navigator.py is one folder up from this script. Look there, wherever the
# project lives, instead of a hard-coded path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import anthropic
from navigator import MODEL, SYSTEM_PROMPT, build_message, time_stamp

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--overnight", action="store_true",
                    help="7:15 AM now, last message at 10:15 PM the night before")
args = parser.parse_args()

if args.overnight:
    # Pretend it's 7:15 AM today, and the last message was 10:15 PM last night.
    now = datetime.now().replace(hour=7, minute=15, second=0, microsecond=0)
    earlier = (now - timedelta(days=1)).replace(hour=22, minute=15)
else:
    now = datetime.now()
    earlier = now - timedelta(hours=9)  # the faked previous message

# A short earlier exchange, stamped at the earlier time.
history = [
    {"role": "user",
     "content": build_message("Thanks, that's all for now.", time_stamp(earlier, None))},
    {"role": "assistant",
     "content": "You're welcome. I'm here whenever you need me."},
]

# The new message, with the gap in its stamp.
new_message = build_message("Hi, I'm back.", time_stamp(now, earlier))
history.append({"role": "user", "content": new_message})

print("--- Sent to Claude ---")
print(new_message)

response = anthropic.Anthropic().messages.create(
    model=MODEL, max_tokens=16000, system=SYSTEM_PROMPT, messages=history,
)
reply = "".join(b.text for b in response.content if b.type == "text")
print("\n--- Navigator replied ---")
print(reply)
print(f"\n[stop_reason: {response.stop_reason}, tokens in: "
      f"{response.usage.input_tokens}, out: {response.usage.output_tokens}]")
