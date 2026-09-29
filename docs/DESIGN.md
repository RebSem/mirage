# Design

How Mirage looks, why, and how the Liquid Glass window is put together. For
threads, modules and data, see [ARCHITECTURE.md](ARCHITECTURE.md).

## The idea

Mirage should feel like a small Apple app you already know how to use: one
window, your video (or your photo) front and centre, faces you can grab with
one click, and a single obvious button. The glass is there to make it feel at home on macOS 26
and to make the window glow with the colours of your own video. It is never
there at the cost of clarity or frame rate.

## Layout

Roughly (the widgets in `mirage/ui/` are the source of truth):

```
 ● ● ● Mirage  ● Ready [Live|Photos & videos]  Zoom camera: “OBS…” (?)
┌──────────────────────────────────────────────┐ ┌─────────────────┐
│                                              │ │  Faces          │
│                                              │ │  ◯ Me   ◯ 1     │
│                 stage                        │ │  ◯ 2    ◯ 3     │
│             (live preview)                   │ │  + Add  Random  │
│                                              │ │  ─────────────  │
│                                              │ │  Look           │
└──────────────────────────────────────────────┘ │  Fast|Bal|Best  │
┌──────────────────────────────────────────────┐ │  Strength ──●   │
│ (cam) camera ⌄  [ ▶ Start ]           mirror │ │  More options ⌄ │
└──────────────────────────────────────────────┘ └─────────────────┘
      glass control bar                              glass sidebar
```

- **Top bar** (next to the traffic lights, no glass): the app name and the
  status pill on the left; the mode switch (**Live | Photos & videos**, a
  248×28 pt segmented control with a sliding highlight) in the middle of the
  window; the virtual camera hint and a help button that opens the matching
  troubleshooting section on the right. The switch is centred on the window,
  not on the space that is left, so it stays put when the status text
  changes; on a narrow window it moves only as far as it must to keep 16 pt
  clear of its neighbours. The status pill and the hint are about calls: in
  Photos & videos they show only while a call is running in the background,
  and the help button only in Live.
- **Stage** (left, glass): the live preview. When idle it explains what to do
  next (*Press Start to go live as Anna* once a face is picked, *Pick a face,
  then press Start* before); while you drag photos over the window it shows
  where to drop them.
- **Sidebar** (right, glass): the face library on top and the *Look* settings
  right under it. The face grid is only as tall as its faces (it scrolls only
  when the window is too short) and the spare room collects at the bottom,
  so opening *More options* grows the panel downwards and nothing above it
  moves. Each face tile carries its `1`–`9` shortcut in a small badge, white
  on the selected face.
- **Control bar** (under the stage, glass): the camera menu (with its own
  chevron) on the left, the one big **Start / Stop** button in the middle,
  the mirror toggle on the right.

## Photos & videos

The same window with a second page. The mode switch in the title bar swaps
the stage and the control bar for the Photos & videos ones; the sidebar stays
put, because your faces and the *Look* settings are the same in both modes
(each mode keeps its own selected face, though). *Look* shows only what
changes a file there: *Strength*, *Sharpness*, *Keep my mouth* and
*Smooth edges*. The switch remembers its position between launches, and a
live call keeps going in the background.

```
┌──────────────────────────────────────────────────────────────────┐
│  ● Swapped · hold Space to compare                               │
│ ╭──────────────────────────────────────────────────────────────╮ │
│ │    A┌─      ─┐                  B┏━━━━━━━━━━┓                │ │
│ │                                  ┃          ┃                │ │
│ │     └─      ─┘                   ┗━━━━━━━━━━┛                │ │
│ │                                   (◉) Anna                   │ │
│ ╰──────────────────────────────────────────────────────────────╯ │
└──────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────┐
│ +  people  ◯ Enhance faces  [ Save ]                           ◐ │
└──────────────────────────────────────────────────────────────────┘
```

**The stage** shows the picture fitted into the glass frame, with 12 pt
rounded corners and a hairline edge, and every face marked:

- a letter (A, B, C… from left to right) in a 22 pt round badge on the
  top-left corner of the face, always inside the photo. Letters, not
  numbers, so they never look like the gallery's `1`–`9` shortcuts;
- **will be swapped:** a solid outline with a violet-to-blue gradient
  (2.25 pt, over a soft dark halo so it reads on skin and on white walls),
  the badge filled violet, and a chip with the avatar and name of the face it
  becomes;
- **left as is:** four white corner marks, a dark badge and no chip.
  Hovering brightens the marks, shows a pointing hand and a quiet
  *Choose a face…* chip; the face you clicked glows teal-blue while its menu
  is open;
- chips stay inside the photo and never overlap each other or the state
  chip: each goes 8 pt under its face if it fits there, otherwise just inside
  the bottom of the outline, otherwise above the face;
- a state chip labels the photo, above its top-left corner when there is
  room and on the corner otherwise: *Swapped · hold Space to compare* after
  a swap, *Original* (the light chip) while you compare, when the face marks
  are hidden too.

The other states of the stage:

- **Empty:** a dashed drop zone with a photo icon, *Drop photos or a video
  here* and *Or press Open. Several photos or a whole folder work too.*, and
  at the bottom *Pick who to become on the right · ⌘⇧O opens files*. The
  whole zone is clickable (it opens files) and brightens on hover. The icon
  and text sit exactly where the Live stage's idle ones do, so switching
  modes doesn't jump. While files are dragged over it, the stage dims behind
  a dashed accent frame.
- **Busy:** the photo dims and the busy capsule (below) in its middle says
  what is happening (*Finding faces…*, *Swapping faces…*, *Making the
  video…*); for a video also a progress bar and *Frame 120 of 900 · 13 fps ·
  1:00 left*.
- **Batch:** the batch list (below).

**Choosing faces.** Clicking a face opens a menu: *Face B · woman, about 30*
as a header, **Leave as is**, then the gallery faces with round avatars, the
most natural-looking first and the best ones marked *★ good match*. The
current choice is ticked. Clicking a face in the gallery (or `1`–`9`) works
here too; `Esc` or a click elsewhere drops the highlight.

**The control bar** is the same component as in Live, left to right:
**Open…** (+, only once something is open: before that the big button says
*Open…*); **Give everyone Anna’s face** (two people, only with two or more
faces); the **Enhance faces** switch and its label (the tooltip says
*Enhance faces (slower)* for a video, where it is a separate setting); the
primary button in the middle; **compare** (a half-filled circle, once a
photo is swapped) and **Show in Finder** (a folder) on the right. The folder
button appears only where the big button says something else: after a video
(the big button says **Play video**) or after a cancelled batch that saved
some photos (**Continue · N left**). Otherwise the big button itself says
**Show in Finder**.

**One primary button that always shows the next step.** It never offers
something that can't be done:

| Opened | The button reads |
|---|---|
| nothing | **Open…** |
| a photo | **Swap** → **Save** → **Show in Finder** |
| several photos or a folder | **Swap in N photos** → **Cancel** (while it runs) → **Show in Finder** |
| a video | **Make video** → **Cancel** (while it runs) → **Play video** |
| a photo or video with no faces | **Open another…** |
| faces, but nobody set to be swapped | *Pick a face on the right* (muted) |

While a photo is being read, swapped or saved, the button names the step
next to a spinner (*Finding faces…*, *Swapping faces…*, *Saving…*) and can't
be clicked. The muted *Pick a face on the right* can: it explains in a toast.
Changing who becomes whom, **Enhance faces** or a *Look* setting after a
swap takes it back to **Swap**, because the result on screen no longer
matches.

**Hold to compare.** Press and hold the compare button, or hold `Space`, to
see the original; let go to see the result again. It is a hold, not a
toggle, so you can never forget which one you are looking at, and the chip
says *Original* while you hold. (`Space` is Start / Stop only in Live.)

## Components

The shared pieces live in `mirage/ui/widgets.py`; sizes are in points.

**Control bar** (`ControlBar`). A glass bar 76 pt tall with 18 pt side
margins, holding a left group, a right group and one centre widget, the
primary button. The button sits in the exact middle of the bar, not of the
space between the groups, so it never shifts when a button next to it
appears or disappears. If it would come within 16 pt of a group, the widgets
marked collapsible fold away first (the *Enhance faces* label, which stays
on as the switch's tooltip); only if that is still not enough does the
button slide aside, and never over a group. The bar decides from sizes
alone, not from what is visible at the moment, so it doesn't flip back and
forth.

**Primary button.** A pill 52 pt tall and at least 220 pt wide (wider for a
long label), with an 18 pt icon and a 15 pt semibold label. Four looks: a
violet-to-blue gradient for the next step, red for **Stop** and **Cancel**,
translucent white with a spinner while busy (not clickable), and
translucent white with an icon for a hint such as *Pick a face on the
right*. A glassy sheen on its upper half brightens on hover; it shrinks to
96.5 % while pressed.

**Icon buttons.** Round, 36 pt in the control bars and 24 pt for help in the
title bar, with a faint white fill that brightens on hover. The camera icon
next to the camera menu is a label, not a button. A toggle that is on (the
mirror) is a quiet ring: a teal-blue edge and icon over a slightly brighter
fill, not a solid coloured disc.

**Chips.** One spec for every small label over video or a photo
(`draw_chip()`): 26 pt tall, fully rounded, 12 pt text (semibold for names
and states), with an optional 8 pt status dot or a 20 pt round avatar. Three
tones: *dark*, the default (near-black at about 70 %, a faint white edge,
white text); *quiet* (a little more see-through, secondary text: hints and
counts); and *light* (white with dark text: *Original*). Live uses them 16 pt
in from the stage's edges for *LIVE* (a red dot), the fps, the face's name
and *Looking for your face…*; Photos & videos for the face chips, the state
chip, the batch count pills and the status on each batch row.

**Status pill.** 26 pt tall in the title bar: an 8 pt dot and a short status
(*Ready*, *Loading models…*, *Live · 14 fps*). The dot breathes, a slow 2 s
pulse, while models load, while the camera starts and while you are live.
Its width is measured with every digit as wide as the widest one, so a
changing fps count never makes it wobble.

**Disclosure row.** *More options* in the *Look* section is a full-width,
30 pt row, not an on/off switch: a 12.5 pt label in the secondary colour
(white on hover and while open) and a chevron at the right edge, where the
switches line up: ⌄ closed, ⌃ open. Open, it shows *Swap everyone in view*,
*Fix blue tint*, *Smooth edges* and *Show fps* under it. In Photos & videos
the row is hidden and *Smooth edges* shows directly under the rest.
*Strength* and *Sharpness* explain themselves in a tooltip.

**Toasts.** Dark rounded capsules (16 pt radius, up to 460 pt wide) with a
dot in the colour of their level: teal-blue for info, yellow for a warning,
red for an error. They are centred over the stage and float 18 pt above the
control bar, so they never cover its buttons; up to three stack upwards, the
newest at the bottom. A click dismisses one.

**Busy capsule** (Photos & videos). A dark capsule (18 pt radius) in the
middle of the photo, which dims behind it, or of the stage when there is no
photo yet: a 22 pt spinner ring and 13.5 pt semibold words. It is 48 pt tall
(62 pt when the words wrap onto two lines) and 200–520 pt wide. For a video
it grows by a 5 pt violet-to-blue progress bar and a line with the frames,
the speed and the time left, and is at least 340 pt wide.

**Batch list** (Photos & videos). A column up to 720 pt wide in the middle
of the stage:

- a header with the title, *N photos* (17 pt semibold), and a subtitle under
  it that follows the job: who everyone becomes (*The main face in each
  becomes Anna*), then *Swapping faces… 2 of 3*, then *Done · saved next to
  the originals* or *Stopped · N left*;
- quiet count pills on the right of the header (*Saved 2*, *No face 1*,
  *Failed 1*), each only once it is above zero; *No face* includes
  *Skipped*;
- a 4 pt progress bar under the header while it runs;
- one row per photo, 56 pt tall with 8 pt between rows and a 14 pt radius: a
  40 pt thumbnail, centre-cropped so it is never squeezed; the file name,
  shortened in the middle if it is long; an error's detail in small grey
  text under the name; and a status pill on the right with a coloured dot:
  grey *Waiting*, teal-blue *Swapping…*, green *Saved*, yellow *No face*,
  grey *Skipped*, red *Failed*.

The row being worked on gets a teal-blue edge and is kept in view; otherwise
the wheel scrolls the list a row at a time, with a thin scroll indicator on
the right. When the list is on screen, a finished batch doesn't also pop a
toast; one appears only if something failed or the window isn't showing the
list.

## How the Liquid Glass works

Qt cannot draw Apple's Liquid Glass; only AppKit's
[`NSGlassEffectView`](https://developer.apple.com/documentation/appkit/nsglasseffectview)
can. Qt, on the other hand, draws *all* of its widgets into one AppKit view
(`QNSView`). Mirage puts those two facts together in `mirage/glass.py`:

1. The Qt window is made transparent: clear background, not opaque, a
   full-size content view under a transparent title bar, and the dark
   appearance.
2. Native views are inserted into the window's frame view **below** Qt's view.
   Wherever Qt paints nothing, you see straight through to them.
3. For every widget that should be glass, `GlassWindow.add(widget, radius)`
   keeps one `NSGlassEffectView`, with the same corner radius, exactly behind
   that widget. The widget itself paints a transparent background.

Native view order inside the window frame, bottom to top:

```
NSVisualEffectView     behind-window blur: the desktop, softly
ambient layer          a tiny, blurred copy of your live video (colour glow)
NSGlassEffectView …    one per registered widget, kept exactly behind it
QNSView                all Qt widgets, transparent background
```

**Keeping glass and widgets together.** An event filter watches every
registered widget (and the window) for move, resize, show, hide and layout
changes. Any of those queues one sync on the next turn of the event loop, so a
burst of layout events costs a single update. The sync maps each widget's
position into the window, flips it from Qt's top-left to AppKit's bottom-left
coordinates, and sets the glass view's frame; hidden widgets hide their glass.

## The ambient layer

The ambient layer is what makes the glass feel alive: it refracts the colours
of *your* video, so the window glows warm under a desk lamp and blue under a
monitor.

- While you are live, about three times a second it takes a frame, shrinks
  it to 40×24 pixels, blurs it, boosts saturation and darkens it a little so
  white text on the glass stays readable.
- Core Animation scales it up to the whole window with smooth filtering and
  cross-fades between updates, so there is no flicker.
- It sits at slightly less than full opacity, letting a hint of the desktop
  blur through.
- Before the camera starts, it shows a soft brand glow (indigo, violet, teal)
  instead.

It is deliberately cheap: a 40×24 image is nothing next to the face swap, and
the scaling and blending happen on the GPU.

## Fallback on older macOS

`NSGlassEffectView` exists only on macOS 26 and newer. Mirage checks for it at
start-up and also respects **System Settings → Accessibility → Display →
Reduce transparency**. If glass is not available, or anything goes wrong while
setting up the native views (Mirage logs that), it falls back: the window
paints an opaque dark background, and the same panels paint a translucent
fill with a faint edge themselves. Same layout, same controls, just flatter.
Looks are never a reason to crash.

## Design rules

1. **One primary action.** *Start / Stop* is the only big, coloured button
   in Live; in Photos & videos the one big button always shows the next step.
   Everything else is secondary and can be ignored on day one.
2. **Words for every state.** The user should never have to guess: *Loading
   models…*, *Starting camera…*, *Live* with the fps, *Looking for your
   face…*, *Zoom camera: “OBS Virtual Camera”*, *Swapping faces…*. A spinner
   alone is not a status, and a button never offers what can't be done yet:
   it says what is missing instead (*Pick a face on the right*).
3. **Toasts, not modal errors.** Problems appear as a short toast above the
   control bar that says what happened and what to do (“No face found in
   ‘beach.jpg’. Try a clear, front-facing photo.”). No error dialog ever pops
   up during a call; the only dialogs are the ones you ask for, like renaming
   or removing a face. A toast doesn't repeat what the screen already shows
   (a finished batch list needs none).
4. **Faces are the content.** Big round thumbnails you can recognise at a
   glance; `1`–`9` match their order, `0` is always you. Faces found in a
   photo get letters instead, so the two never get mixed up.
5. **Keyboard first, mouse friendly.** Every common action has a shortcut
   (see the [README](../README.md#keyboard-shortcuts)); everything also works
   with a click or a drag.
6. **No surprises on the call.** Mirroring affects the preview only; the
   virtual camera is always 1280×720 and never restarts while live.
7. **Never touch the original.** Photos and videos are only read; every
   result gets a new name next to the original, and a cancelled video leaves
   nothing behind.
8. **Always dark.** The whole app (glass, menus and dialogs) is forced to the
   dark appearance and the palette is tuned for white text over tinted glass,
   because video looks best in dark surroundings.
9. **Both languages, always.** Every string exists in English and Russian
   (`mirage/i18n.py`).

## Tokens

The current values live in `mirage/theme.py`; this is the intent behind them.

| Token | Value | Use |
|---|---|---|
| Accent | `#8B7CFF` soft violet, to `#5AC8FA` teal-blue | slider fill, switches, progress bars, faces that will be swapped; the primary button uses a slightly deeper `#7C6CFF` → `#3FA7F5` |
| Live | `#FF453A` (system red, dark) | live badge, Stop |
| Ready | `#32D74B` (system green, dark) | ready and connected states |
| Text | white at ~92% / ~67% / ~48% | primary / secondary / tertiary |
| Radii | 28–30 pt; 12 pt; fully round | panels, stage, control bar; the photo in Photos & videos; buttons, chips, pills |
| Spacing | 16 pt margins, 14 pt gaps | everywhere |

### Motion

Motion is short and quiet; it confirms an action and gets out of the way.

| What | Duration |
|---|---|
| Button press feedback | 120 ms |
| Toggles, segmented highlight | 160 ms |
| Toast in / out | 220 ms / 160 ms |
| Ambient glow cross-fade | about 0.5 s while live, 0.6 s back to the idle glow |

With **Reduce motion** turned on in macOS, button presses and toggles change
instantly and toasts fade without sliding.

## Adding a glass panel

1. Use a `GlassPanel` (`mirage/ui/widgets.py`), or any widget with a
   transparent background.
2. Register it with `glass.add(widget, radius)`, using a radius from
   `mirage/theme.py`.
3. `GlassWindow.install()` runs once after the window is shown and creates the
   native views; panels added later get their glass immediately. After it
   runs, set `panel.native_glass = glass.native`, so the panel paints the
   fallback fill only when there is no native glass.
4. Check both paths: macOS 26+ with glass, and *Reduce transparency* turned on
   (which exercises the fallback).
