"""Full-screen translucent overlay for selecting a capture area with the mouse.

Uses tkinter (stdlib). Must be called from the thread that owns the event loop
of the client (the main thread); it blocks until the user finishes.
"""

from __future__ import annotations

import tkinter as tk

from client.capture import Region, virtual_screen

MIN_SIZE = 50


def select_region() -> Region | None:
    """Drag a rectangle with the left mouse button. Esc or right click cancels."""
    screen = virtual_screen()
    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{screen.width}x{screen.height}+{screen.left}+{screen.top}")
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.3)
    root.configure(cursor="crosshair")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_text(
        screen.width // 2,
        40,
        text="Выделите область с доской. Esc — отмена",
        fill="white",
        font=("Segoe UI", 20),
    )

    result: list[Region] = []
    start: list[tuple[int, int]] = []
    rect_id: list[int] = []

    def on_press(event: tk.Event) -> None:
        start[:] = [(event.x_root, event.y_root)]
        rect_id[:] = [canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="red", width=3)]

    def on_drag(event: tk.Event) -> None:
        if not start:
            return
        x0, y0 = start[0]
        canvas.coords(
            rect_id[0],
            x0 - screen.left,
            y0 - screen.top,
            event.x_root - screen.left,
            event.y_root - screen.top,
        )

    def on_release(event: tk.Event) -> None:
        if not start:
            return
        x0, y0 = start[0]
        x1, y1 = event.x_root, event.y_root
        left, top = min(x0, x1), min(y0, y1)
        width, height = abs(x1 - x0), abs(y1 - y0)
        if width >= MIN_SIZE and height >= MIN_SIZE:
            result.append(Region(left, top, width, height))
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda _e: root.destroy())
    canvas.bind("<ButtonPress-3>", lambda _e: root.destroy())
    root.focus_force()
    root.mainloop()
    return result[0] if result else None
