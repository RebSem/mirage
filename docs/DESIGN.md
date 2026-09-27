# Design

How Mirage looks, why, and how the Liquid Glass window is put together. For
threads, modules and data, see [ARCHITECTURE.md](ARCHITECTURE.md).

## The idea

Mirage should feel like a small Apple app you already know how to use: one
window, your video front and centre, faces you can grab with one click, and a
single obvious button. The glass is there to make it feel at home on macOS 26
and to make the window glow with the colours of your own video. It is never
there at the cost of clarity or frame rate.

## Layout

Roughly (the widgets in `mirage/ui/` are the source of truth):

```
 ● ● ●  Mirage  ● Ready               Zoom camera: “OBS Virtual Camera”  (?)
┌──────────────────────────────────────────────┐ ┌─────────────────┐
│                                              │ │  Faces          │
│                                              │ │  ◯ Me   ◯ 1     │
│                 stage                        │ │  ◯ 2    ◯ 3     │
│             (live preview)                   │ │  + Add  Random  │
│                                              │ │                 │
│                                              │ │  Look           │
└──────────────────────────────────────────────┘ │  Fast|Bal|Best  │
┌──────────────────────────────────────────────┐ │  blend, sharp…  │
│  camera ▾          [   Start   ]      mirror │ │                 │
└──────────────────────────────────────────────┘ └─────────────────┘
      glass control bar                              glass sidebar
```

- **Top bar** (next to the traffic lights, no glass): the app name, the
  status pill, the virtual camera hint and a help button that opens the
  matching troubleshooting section.
- **Stage** (left, glass): the live preview. When idle it explains what to do
  next; while you drag photos over the window it shows where to drop them.
- **Sidebar** (right, glass): the face library on top, the *Look* settings
  below it.
- **Control bar** (under the stage, glass): the camera menu, the one big
  **Start / Stop** button and the mirror toggle.

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

1. **One primary action.** *Start / Stop* is the only big, coloured button.
   Everything else is secondary and can be ignored on day one.
2. **Words for every state.** The user should never have to guess: *Loading
   models…*, *Starting camera…*, *Live* with the fps, *Looking for your
   face…*, *Zoom camera: “OBS Virtual Camera”*. A spinner alone is not a
   status.
3. **Toasts, not modal errors.** Problems appear as a short glass toast that
   says what happened and what to do (“No face found in ‘beach.jpg’. Try a
   clear, front-facing photo.”). No error dialog ever pops up during a call;
   the only dialogs are the ones you ask for, like renaming or removing a
   face.
4. **Faces are the content.** Big round thumbnails you can recognise at a
   glance; `1`–`9` match their order, `0` is always you.
5. **Keyboard first, mouse friendly.** Every common action has a shortcut
   (see the [README](../README.md#keyboard-shortcuts)); everything also works
   with a click or a drag.
6. **No surprises on the call.** Mirroring affects the preview only; the
   virtual camera is always 1280×720 and never restarts while live.
7. **Always dark.** The whole app (glass, menus and dialogs) is forced to the
   dark appearance and the palette is tuned for white text over tinted glass,
   because video looks best in dark surroundings.
8. **Both languages, always.** Every string exists in English and Russian
   (`mirage/i18n.py`).

## Tokens

The current values live in `mirage/theme.py`; this is the intent behind them.

| Token | Value | Use |
|---|---|---|
| Accent | `#8B7CFF` soft violet, to `#5AC8FA` teal-blue | primary button, slider fill |
| Live | `#FF453A` (system red, dark) | live badge, Stop |
| Ready | `#32D74B` (system green, dark) | ready and connected states |
| Text | white at ~92% / ~59% / ~37% | primary / secondary / tertiary |
| Radii | 28–30 pt | panels, stage, control bar |
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
