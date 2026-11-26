# Live Focus and Autofocus

The live focus page shows the camera's picture as it is taken and measures how sharp the stars are. With a [focuser motor](Focuser-Device) it can also focus the lens for you with one button.

Normal sky pictures pause while a focus session runs, and resume on their own when it ends. Nothing taken during a session is saved, uploaded or added to timelapses.

---

## 1. What you need

* **A camera indi-allsky can command.** The table shows what each camera type gets.
* **An admin account, on the admin network.** Starting a session and moving the lens use the same rule as the focuser buttons on the Focus page. Any logged-in user can watch a running session.
* **The web interface and the capture service on the same machine.** They talk over a local socket. If they run in separate containers or on separate machines, the Focus page says so and offers only the classic view.
* **Optional: a focuser motor.** Without one you focus by turning the focus ring and watching the star size. With one you get the lens buttons and **Autofocus**.

| Camera | Picture |
|---|---|
| `indi` camera whose sensor is on the starlight list and whose driver streams video (today: ZWO ASI676MC) | Live video, about 10 pictures a second |
| Any other `indi` camera | Still pictures, taken back to back |
| Raspberry Pi cameras (`libcamera_*`), `mqtt_*`, `indi_accumulator` | Still pictures, taken back to back |
| `indi_passive`, `pycurl_camera` | No live page. The classic Focus page stays. |
| Test cameras | Simulated live video |

The line under the picture always says which picture mode is in use and why.

The starlight list covers sensors whose maker documents both a low-light family (Sony STARVIS or STARVIS 2) and 10 or more pictures a second. These are IMX676, IMX462, IMX290, IMX327, IMX335, IMX678 and IMX585. An `indi` camera reports only its device name, so each camera model is also mapped to its sensor. Today the only mapped model is the ZWO ASI676MC.

---

## 2. Open the page

Either:

* Go to **Tools** → **Focus** and press **Live Focus** at the top of the page. If the button is missing, the page shows the reason in its place.
* Or go straight to **Tools** → **Focus** → **Live**. If this camera cannot run live focus, you land on the Focus page with the reason.

The live page is at `/indi-allsky/focus/live`. **← Focus**, in the same spot, returns to the classic view.

Until a session starts, the page shows the last sky picture with a **▶ Start Live Preview** button on it. The focus controls sit underneath, greyed out. Starting a session asks first, because it pauses sky pictures. A running session shows a red **LIVE** tag on the picture.

Every question the page asks puts the safe answer first and selects it. Pressing Esc or tapping outside the question gives that answer.

With a focuser configured but its gear teeth or lens travel limit not set, the lens buttons and **Autofocus** stay off and the page says which setting to fill in. See [Settings](#7-settings).

---

## 3. Focus with a motor: Autofocus

1. Turn the focus ring by hand until the stars are roughly sharp. Autofocus searches around wherever the lens is when it starts.
2. Press **Autofocus** and confirm. Sky pictures pause.
3. Wait. The step list shows each step as it runs:
   * **Tune exposure:** the camera tries a range of exposures and gains and keeps the shortest one that shows most of the stars. This takes about 20 to 40 seconds.
   * **Pick stars:** three pictures are stacked and the stars to measure are chosen. Moon glare and lens reflections are left out.
   * **Autofocus:** the lens moves inward, then makes one slow outward sweep while every picked star is measured. A curve is fitted to the star sizes, and the lens moves to the lowest point of the curve.
   * **Check focus:** look at the stars. If they are not sharp, step the lens in or out, or run Autofocus again.
4. Press **Save autofocus results** to keep the lens where it is and end the session.

A good fit also resizes the steps: **Fine** becomes a quarter of the in-focus range and **Medium** the whole range, and Fine is selected. Running **Autofocus** again after a fit asks first.

Press **Cancel** at any time. It asks **End without saving?** with **Keep going** selected. **End session** puts the lens back where it was when the session started.

---

## 4. Preview, and focusing by hand

**▶ Start Live Preview** tunes the exposure and then shows the live picture. Use it to watch the picture while you focus yourself.

* **With a motor:** **Step in** and **Step out** under **Focus controls** move the lens one step each press. **Step size** sets how far, in degrees of the focus ring: **Fine** 0.8°, **Medium** 3.5° (the default) or **Coarse** 13°, until an autofocus fit resizes Fine and Medium. Press **Autofocus** at any point; it picks the stars first.
* **Without a motor:** turn the focus ring slowly. After the tune the stars are picked, and the number beside the picture shows their size. Smaller is sharper. Stop where it is lowest.

Press **Save focus** when you are done, or **Cancel**.

The lens buttons and Save are off while the exposure tunes or the stars are picked. Cancel always works.

---

## 5. Advanced

Turn on **Advanced** for more controls. The browser remembers the setting.

| Control | What it does |
|---|---|
| Graph | Star size against lens position, one point per star per picture. It appears once an autofocus starts. Click or drag the focus line to move the lens there. |
| **Best fit** | Move the lens to the lowest point of the fitted curve. |
| **Back** | Move the lens to where it was before the last move. |
| **Clear graph** | Remove the points. |
| **Exposure**, **Gain**, **Apply** | Set the exposure and gain yourself. Apply stops a running tune and keeps your values. |
| **Tune** | Run the exposure tune again. |
| **Stretch** | **Auto** sets the picture's levels once (**Re-level** sets them again), **Manual** uses the Black and White sliders, **Off** shows the raw picture. It changes the picture only, for everyone watching. The measurements stay the same. |
| **Move region** | Live video shows a 1024 × 1024 part of the sensor. Drag the box over a whole-sensor picture to choose another part, for example away from the moon. |
| **Stars** menu | **Star brightness ≥** greys out faint stars, so they are not measured. **Pick stars again** chooses new stars. |
| Star rings | Tap a numbered ring to stop measuring that star. Tap again to measure only that star. Tap a third time to measure it with the others again. |

When no stars are found, the number shows a contrast score instead of a star size. Bigger is sharper. Autofocus needs stars and stays off until it has them.

---

## 6. When a session ends

A session ends when you press **Save** or **Cancel**, or:

* when no focus page has been open for 2 minutes. Reopening the page within that time rejoins the same session.
* when nobody has touched the page for 15 minutes. A warning with a **Keep going** button shows for the last minute.
* when the capture service stops or reloads, or the camera fails.

The camera's normal exposure and gain are put back, and normal pictures resume on the next pass. The page says why the session ended.

---

## 7. Settings

The lens settings are under **Configuration** → **Focuser**. With a focuser selected, Config will not save until both gear counts and the travel limit are set.

| Setting | Default | What it does |
|---|---|---|
| **Motor Gear Teeth** | 0 (unset) | Teeth on the gear the motor turns. Allowed range 1 to 1000. |
| **Lens Gear Teeth** | 0 (unset) | Teeth on the gear around the focus ring. With the motor gear, this turns motor steps into degrees of the ring. If the motor turns the ring directly, give both the same number. Allowed range 1 to 1000. |
| **Lens Travel Limit (lens degrees each way)** | 0 (unset) | How far the focus ring may turn inward or outward from where it was when the session started. Nothing crosses it, Autofocus included. Allowed range 1 to 3600. |
| **Backlash (motor degrees)** | 30 | The free play in the gears between the motor and the focus ring. Every move ends travelling outward, and a move that ends inward first goes past its target by more than this, so backlash never decides where the lens stops. Must be less than the whole lens travel, counted in motor degrees. |

For example, a motor gear of 12 teeth driving a ring gear of 82 teeth turns the motor 6.8 times for one turn of the ring.

The position is counted from the start of each session, because a stepper motor has no fixed zero. Turning the focus ring by hand during a session makes the count wrong.

The web interface and the capture service meet on a socket at `/var/lib/indi-allsky/focus-session.sock`. To use another path, set `INDI_ALLSKY_FOCUS_ADDRESS` in `flask.json`. Both services must see the same path.

---

## 8. Messages

| Message | What to do |
|---|---|
| No stars to measure. Try a longer exposure. | Increase the exposure under Advanced, or wait for darker sky. |
| The picture is over-exposed. Try a shorter exposure. | Decrease the exposure, or press Tune. |
| The picked stars are saturated. Try a shorter exposure. | Decrease the exposure, then **Pick stars again**. |
| Best focus may be beyond the travel limit. | Turn the focus ring by hand toward focus, then run Autofocus again. Or raise the travel limit. |
| Could not find a clear best focus. | The sizes did not form a curve. Check the stars are real stars and not glare, then run Autofocus again. |
| The region moved away from a bright light (the moon?). | The live region was placed away from glare. Use Move region to choose another. |
| The live focus page cannot reach the capture program. | Start the capture service, or run the web interface on the same machine as capture. |
| Live focus and autofocus need a camera this program can command. | The camera type cannot be commanded. Use the classic Focus page. |
