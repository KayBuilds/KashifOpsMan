# Drift

A Windows tray utility inspired by Tangerine. Start dragging a file, hold **Shift**, and a radial
wheel opens at the cursor. Drop the file on a wedge to convert or edit it. Everything runs offline.

**Status: Phase 1.** The tray app, drag + Shift detection, and an *empty* wheel are in. Dropping a
file on the wheel only shows a toast. Your files are never touched.

## Run (Windows, Python 3.12)

```powershell
cd drift
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m drift --debug          # add --show-probe to tint the invisible probe window pink
```

The log is written to `%LOCALAPPDATA%\Drift\drift.log` (tray menu → *Open log folder*).

## How detection works

1. A low-level mouse hook (`WH_MOUSE_LL`, ctypes, on its own thread) notices when a button is held
   and the cursor moves past the system drag threshold. While that is happening, the modifier keys
   are polled every 10 ms.
2. When Shift goes down, the wheel window appears under the cursor as an invisible **probe**
   (alpha 3/255: you can't see it, but it still catches the drag). It is a real OLE drop target, and
   Drift nudges the cursor 1 px and back so OLE checks it straight away.
3. If a real file drag is in progress, OLE sends the probe `DragEnter` with the file list, and the
   wheel animates in (120 ms). If it gets anything else (text, virtual files, or no OLE drag at
   all, such as a rubber-band selection or a window move), it gets out of the way within 400 ms.
4. Every drop answers **Copy**, even though Shift makes Explorer offer *Move*, so Explorer never
   deletes or moves the original.

## Phase 1 test checklist

| # | Do this | Expected |
|---|---------|----------|
| 1 | Start Drift | Orange wheel icon in the tray, no window |
| 2 | Tray → *Show test wheel* | Wheel at the cursor, closes after 3 s or on click |
| 3 | Drag a file from Explorer, **then** hold Shift | Wheel animates in, centred on the cursor, showing the file name and size |
| 4 | Move over the wedges | The wedge under the cursor lights up |
| 5 | Release Shift while still dragging | Wheel hides; press Shift again and it comes back |
| 6 | Add Ctrl while holding Shift | Switches to the blue 7-wedge TOOLS wheel |
| 7 | Press Esc during the drag | Wheel hides, and Explorer cancels the drag |
| 8 | Drop on a wedge | Toast reads "Dropped on wedge N". The file stays where it was |
| 9 | Drop elsewhere, or release the mouse | Wheel hides |
| 10 | Same as 3, from the Desktop and with several files | Shows "N items" and the total size |
| 11 | Shift + rubber-band select in Explorer, or Shift + drag a window | No wheel ever appears |
| 12 | Shift + drag text in a browser into another app | No wheel; the text drop still works |
| 13 | Run a second copy | Exits immediately (single instance) |
| 14 | Check the log after step 3 | `File drag confirmed NN ms after trigger`. This should be well under 150 ms |

Tip: start the drag *before* pressing Shift, because Shift+click in Explorer changes the selection.

## Tests

```
pip install pytest
pytest tests
```
