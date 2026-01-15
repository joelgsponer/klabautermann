#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "rich",
# ]
# ///

import argparse
import os
import select
import subprocess
import sys
import termios
import time
import tty
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

# Configuration
TASKS_DIR = Path(".")
PENDING_DIR = TASKS_DIR / "pending"
IN_PROGRESS_DIR = TASKS_DIR / "in-progress"
BLOCKED_DIR = TASKS_DIR / "blocked"
COMPLETED_DIR = TASKS_DIR / "completed"

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass
class TaskInfo:
    title: str
    content: str
    metadata: Dict[str, str]
    path: Path


def parse_metadata(lines: Iterable[str]) -> Dict[str, str]:
    """
    Extracts a shallow metadata map (ID, Priority) from the markdown task file.
    """
    meta: Dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line.startswith("- **"):
            continue
        if "**ID**" in line:
            meta["id"] = (
                line.split("**ID**", maxsplit=1)[-1].split(":", maxsplit=1)[-1].strip()
            )
        elif "**Priority**" in line:
            meta["priority"] = (
                line.split("**Priority**", maxsplit=1)[-1]
                .split(":", maxsplit=1)[-1]
                .strip()
            )
    return meta


def get_task_info(file_path: Path) -> TaskInfo:
    """
    Reads a markdown task file and returns a TaskInfo object.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return TaskInfo(
            title=file_path.name,
            content="Error reading file",
            metadata={"id": file_path.name, "priority": "P3"},
            path=file_path,
        )

    title = file_path.name
    content_lines: List[str] = []

    if lines:
        # Try to extract title from the first header
        if lines[0].startswith("# "):
            title = lines[0].strip("# ").strip()
            content_lines = lines[1:]
        else:
            content_lines = lines

    metadata = parse_metadata(lines)
    return TaskInfo(
        title=title, content="".join(content_lines), metadata=metadata, path=file_path
    )


def get_tasks_from_dir(directory: Path) -> List[TaskInfo]:
    """
    Returns a list of TaskInfo objects for all .md files in the directory.
    Sorted by filename to keep order stable.
    """
    if not directory.exists():
        return []

    files = sorted([f for f in directory.glob("*.md")])
    return [get_task_info(f) for f in files]


def configure_body(layout: Layout, include_blocked: bool) -> None:
    columns = [
        Layout(name="pending", ratio=1),
        Layout(name="inprogress", ratio=2),
    ]
    if include_blocked:
        columns.append(Layout(name="blocked", ratio=1))
    columns.append(Layout(name="done", ratio=1))
    layout["body"].split_row(*columns)


def make_layout(include_blocked: bool = True) -> Layout:
    """Define the layout."""
    layout = Layout(name="root")
    layout.split_column(Layout(name="summary", size=3), Layout(name="body"))
    configure_body(layout, include_blocked=include_blocked)
    return layout


def sort_by_priority(tasks: List[TaskInfo]) -> List[TaskInfo]:
    def key(task: TaskInfo) -> Tuple[int, str, str]:
        priority = task.metadata.get("priority", "P3").upper()
        task_id = task.metadata.get("id", task.title)
        return (PRIORITY_ORDER.get(priority, 99), task_id, task.title)

    return sorted(tasks, key=key)


def clamp_offset(offset: int, total: int, page_size: int) -> int:
    if total <= page_size:
        return 0
    offset = max(offset, 0)
    max_offset = max(total - page_size, 0)
    return min(offset, max_offset)


def compute_page_size(layout: Layout, default: int) -> int:
    """
    Estimate how many text rows can fit in a column based on the terminal height.
    Subtract a small buffer for borders/padding and clamp to at least 1.
    """
    try:
        body_height = layout["body"].size.height  # type: ignore[arg-type]
    except Exception:
        body_height = None
    total_height = body_height or console.size.height
    usable = max(total_height - 4, 1)
    return max(default, usable)


def format_task_label(task: TaskInfo, done: bool = False) -> str:
    priority = task.metadata.get("priority")
    task_id = task.metadata.get("id")
    prefix_parts = []
    if priority:
        prefix_parts.append(f"[{priority}]")
    if task_id:
        prefix_parts.append(task_id)
    prefix = " ".join(prefix_parts)
    bullet = "✓" if done else "•"
    if prefix:
        return f"{bullet} {prefix} — {task.title}"
    return f"{bullet} {task.title}"


def generate_summary_panel(
    pending_count: int,
    inprogress_count: int,
    blocked_count: int,
    done_count: int,
    focus: str,
) -> Panel:
    text = Text()
    parts = [
        ("pending", "Pending", pending_count, "yellow"),
        ("inprogress", "In Progress", inprogress_count, "blue"),
        ("blocked", "Blocked", blocked_count, "magenta"),
        ("done", "Done", done_count, "green"),
    ]
    for idx, (key, label, count, style) in enumerate(parts):
        if idx:
            text.append("   ")
        style_value = f"{style} bold" if focus == key else style
        text.append(f"{label}: {count}", style=style_value)
    text.append("\n")
    text.append(
        "Tab/Shift-Tab move column • j/k or ↑/↓ select • e edit • q quit • --once for snapshot",
        style="dim",
    )
    return Panel(text, border_style="cyan", title="Task Monitor")


def generate_list_panel(
    tasks: List[TaskInfo],
    offset: int,
    page_size: int,
    title: str,
    border_style: str,
    empty_message: str,
    focused: bool,
    done: bool = False,
    selected_index: int | None = None,
) -> Panel:
    if not tasks:
        return Panel(empty_message, title=title, border_style=border_style)

    start = clamp_offset(offset, len(tasks), page_size)
    subset = tasks[start : start + page_size]
    lines: List[Text] = []
    for idx, task in enumerate(subset, start=start):
        label = format_task_label(task, done=done)
        if selected_index is not None and idx == selected_index:
            label = f"> {label}"
            line = Text(label, style="reverse")
        else:
            line = Text(f"  {label}")
        lines.append(line)
    subtitle = f"{start + 1}-{start + len(subset)} of {len(tasks)}"
    style = f"bold {border_style}" if focused else border_style
    return Panel(
        Text("\n").join(lines), title=title, border_style=style, subtitle=subtitle
    )


def generate_inprogress_panel(
    tasks: List[TaskInfo],
    offset: int,
    page_size: int,
    focused: bool,
    selected_index: int | None,
) -> Panel:
    if not tasks:
        return Panel(
            "No tasks in progress",
            title="[blue]In Progress[/blue]",
            border_style="blue",
        )

    start = clamp_offset(offset, len(tasks), page_size)
    subset = tasks[start : start + page_size]

    renderables = []
    for idx, task in enumerate(subset, start=start):
        task_content = Markdown(task.content or "No content")
        title_bits = [task.title]
        priority = task.metadata.get("priority")
        task_id = task.metadata.get("id")
        extra = " • ".join(filter(None, [priority, task_id]))
        if extra:
            title_bits.append(f"[dim]{extra}[/dim]")
        border = (
            "bright_cyan"
            if selected_index is not None and idx == selected_index
            else "blue"
        )
        p = Panel(
            task_content,
            title=" — ".join(title_bits),
            border_style=border,
            padding=(1, 2),
        )
        renderables.append(p)
        renderables.append(Text(" "))  # Spacer

    subtitle = f"{start + 1}-{start + len(subset)} of {len(tasks)} (j/k to scroll)"
    style = "bold blue" if focused else "blue"
    return Panel(
        Group(*renderables),
        title="[blue]In Progress[/blue]",
        border_style=style,
        subtitle=subtitle,
    )


@contextmanager
def raw_input_mode(enabled: bool):
    if not enabled:
        yield None
        return
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield (fd, old_settings)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


@contextmanager
def suspend_raw_mode(raw_state: tuple[int, list[int]] | None):
    if raw_state is None:
        yield
        return
    fd, old_settings = raw_state
    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    try:
        yield
    finally:
        tty.setcbreak(fd)


def poll_key(timeout: float, enabled: bool) -> str | None:
    if not enabled:
        time.sleep(timeout)
        return None

    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
    except (ValueError, OSError):
        return None
    if ready:
        first = sys.stdin.read(1)
        if first == "\x1b":
            if select.select([sys.stdin], [], [], 0.01)[0]:
                second = sys.stdin.read(1)
            else:
                return first
            if second == "[":
                if select.select([sys.stdin], [], [], 0.01)[0]:
                    third = sys.stdin.read(1)
                else:
                    return None
                if third == "A":
                    return "up"
                if third == "B":
                    return "down"
                if third == "C":
                    return "right"
                if third == "D":
                    return "left"
                if third == "Z":
                    return "shift_tab"
            elif second == "Z":
                return "shift_tab"
            return None
        if first == "\t":
            return "tab"
        return first
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor task status files.")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="Refresh interval in seconds."
    )
    parser.add_argument("--once", action="store_true", help="Render once then exit.")
    parser.add_argument(
        "--list-page-size",
        type=int,
        default=12,
        help="Rows to show in pending/blocked/done columns before scrolling.",
    )
    parser.add_argument(
        "--inprogress-page-size",
        type=int,
        default=2,
        help="Number of in-progress tasks to render at once.",
    )
    return parser.parse_args()


def run_monitor(args: argparse.Namespace) -> None:
    initial_blocked_visible = len(get_tasks_from_dir(BLOCKED_DIR)) > 0
    layout = make_layout(include_blocked=initial_blocked_visible)
    layout.size = console.size
    focus_order_all = ["pending", "inprogress", "blocked", "done"]
    focus_idx = 1  # start on in-progress
    offsets = {key: 0 for key in focus_order_all}
    selections = {key: 0 for key in focus_order_all}
    enable_input = sys.stdin.isatty() and not args.once
    blocked_visible = initial_blocked_visible

    with raw_input_mode(enable_input) as raw_state:
        with Live(
            layout,
            refresh_per_second=8,
            screen=True,
            console=console,
            auto_refresh=False,
        ) as live:
            while True:
                pending_tasks = sort_by_priority(get_tasks_from_dir(PENDING_DIR))
                inprogress_tasks = get_tasks_from_dir(IN_PROGRESS_DIR)
                blocked_tasks = get_tasks_from_dir(BLOCKED_DIR)
                completed_tasks = get_tasks_from_dir(COMPLETED_DIR)
                layout.size = console.size

                new_blocked_visible = len(blocked_tasks) > 0
                if new_blocked_visible != blocked_visible:
                    blocked_visible = new_blocked_visible
                    configure_body(layout, include_blocked=blocked_visible)

                visible_focus_order = (
                    ["pending", "inprogress"]
                    + (["blocked"] if blocked_visible else [])
                    + ["done"]
                )
                if focus_idx >= len(visible_focus_order):
                    focus_idx = len(visible_focus_order) - 1
                current_focus = visible_focus_order[focus_idx]

                tasks_by_focus = {
                    "pending": pending_tasks,
                    "inprogress": inprogress_tasks,
                    "blocked": blocked_tasks,
                    "done": completed_tasks,
                }
                page_sizes = {
                    "pending": compute_page_size(layout, args.list_page_size),
                    "inprogress": compute_page_size(layout, args.inprogress_page_size),
                    "blocked": compute_page_size(layout, args.list_page_size),
                    "done": compute_page_size(layout, args.list_page_size),
                }

                for key, tasks in tasks_by_focus.items():
                    total = len(tasks)
                    selections[key] = (
                        0
                        if total == 0
                        else min(max(selections.get(key, 0), 0), total - 1)
                    )
                    page_size = page_sizes[key]
                    current_offset = offsets.get(key, 0)
                    if selections[key] < current_offset:
                        current_offset = selections[key]
                    elif selections[key] >= current_offset + page_size:
                        current_offset = selections[key] - page_size + 1
                    offsets[key] = clamp_offset(current_offset, total, page_size)

                layout["summary"].update(
                    generate_summary_panel(
                        len(pending_tasks),
                        len(inprogress_tasks),
                        len(blocked_tasks),
                        len(completed_tasks),
                        current_focus,
                    )
                )
                layout["pending"].update(
                    generate_list_panel(
                        pending_tasks,
                        offsets["pending"],
                        args.list_page_size,
                        title="[yellow]Pending[/yellow]",
                        border_style="yellow",
                        empty_message="No pending tasks",
                        focused=current_focus == "pending",
                        selected_index=selections["pending"],
                    )
                )
                if blocked_visible:
                    layout["blocked"].update(
                        generate_list_panel(
                            blocked_tasks,
                            offsets["blocked"],
                            args.list_page_size,
                            title="[magenta]Blocked[/magenta]",
                            border_style="magenta",
                            empty_message="No blocked tasks",
                            focused=current_focus == "blocked",
                            selected_index=selections["blocked"],
                        )
                    )
                layout["done"].update(
                    generate_list_panel(
                        completed_tasks,
                        offsets["done"],
                        args.list_page_size,
                        title="[green]Done[/green]",
                        border_style="green",
                        empty_message="No completed tasks",
                        focused=current_focus == "done",
                        done=True,
                        selected_index=selections["done"],
                    )
                )
                layout["inprogress"].update(
                    generate_inprogress_panel(
                        inprogress_tasks,
                        offsets["inprogress"],
                        args.inprogress_page_size,
                        focused=current_focus == "inprogress",
                        selected_index=selections["inprogress"],
                    )
                )
                live.refresh()

                if args.once:
                    break

                key = poll_key(args.interval, enable_input)
                if key is None:
                    continue

                if key == "q":
                    break
                if key in {"h", "left", "shift_tab"}:
                    focus_idx = (focus_idx - 1) % len(visible_focus_order)
                elif key in {"l", "right", "tab"}:
                    focus_idx = (focus_idx + 1) % len(visible_focus_order)
                elif key in {"j", "down"}:
                    selections[current_focus] += 1
                elif key in {"k", "up"}:
                    selections[current_focus] -= 1
                elif key == "e":
                    tasks = tasks_by_focus[current_focus]
                    if not tasks:
                        continue
                    selection = selections[current_focus]
                    if selection < 0 or selection >= len(tasks):
                        continue
                    task = tasks[selection]
                    live.stop()
                    with suspend_raw_mode(raw_state):
                        editor = (
                            os.environ.get("VISUAL")
                            or os.environ.get("EDITOR")
                            or "nano"
                        )
                        try:
                            subprocess.run([editor, str(task.path)], check=False)
                        except FileNotFoundError:
                            console.print(f"Editor '{editor}' not found.", style="red")
                        except Exception as exc:
                            console.print(f"Failed to open editor: {exc}", style="red")
                    live.start(refresh=True)
                # Ignore unknown keys and refresh on next loop


if __name__ == "__main__":
    run_monitor(parse_args())
