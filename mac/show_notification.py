import subprocess
import sys


def _applescript_str(text):
    """Escape a Python string for use inside an AppleScript string literal."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def notify(title, message):
    script = (
        f'display notification "{_applescript_str(message)}" '
        f'with title "{_applescript_str(title)}"'
    )
    subprocess.run(["osascript", "-e", script], check=True)


if __name__ == "__main__":
    title = sys.argv[1] if len(sys.argv) > 1 else "Battery Buddy"
    message = sys.argv[2] if len(sys.argv) > 2 else "Test notification"
    notify(title, message)
    print("Notification sent.")
