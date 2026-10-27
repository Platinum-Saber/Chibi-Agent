# Add a 3D model (her serious form and the Rimuru / Raphael outfits)

Raphael's 3D body is drawn by Godot (shipped with the app), but **no 3D model ships**: the models used during development can't be redistributed. Without one she stays in her chibi form. With one:
- `raphael.vrm` becomes her **serious form**: she transforms from the chibi into it for work, alerts and "serious mode", and it's the **Raphael** outfit;
- `rimuru.vrm` is the **Rimuru** outfit.

## 1. Get a VRM
Any humanoid VRM (0.x or 1.0) works, for example one made in VRoid Studio. **Check its licence**: use it only as its terms allow, and don't redistribute a model whose licence forbids it.

## 2. Put it in place
Copy the file into the app's `overlay3d\models\` folder with one of these names:

```
%LOCALAPPDATA%\Programs\Raphael\overlay3d\models\raphael.vrm
%LOCALAPPDATA%\Programs\Raphael\overlay3d\models\rimuru.vrm
```

Restart Raphael (tray → Restart agent). The first start with a new model takes up to 30 s while Godot imports it. Uninstalling keeps this folder.

## 3. Use it
- Tray → **Switch to 3D model** (or Customize → Look) wears it full-time; **Switch to 2D art** goes back.
- Tray → **Outfit** picks Rimuru or Raphael.
- In the chibi outfit she turns into the 3D Raphael when she works; say "chibi mode" / "serious mode" to stay in one form.
- Middle-drag turns her; Customize → Look sets her height and walking pace.

## Motions (optional)
Without extra files she uses simple built-in motions. Better ones come from [Mixamo](https://www.mixamo.com) (free with an Adobe account; Adobe allows them in your projects, not redistribution as raw files, so none ship):
1. Download each take as **FBX, Without Skin, 30 fps** ("In Place" for walks).
2. Copy them to `overlay3d\anims\mixamo\`.
3. `overlay3d\clip_sources.cfg` lists which takes play each slot (idle, talk, think, dances, landings…); the file names there are the ones it looks for. Details: `overlay3d\README.md` → Her clips and expressions.

## Troubleshooting
`%LOCALAPPDATA%\ChibiAgent\logs\godot3d.log` is the renderer's log, and `overlay.log` says when an outfit is skipped ("model not found") or when the renderer couldn't start (she then goes back to the 2D body).
