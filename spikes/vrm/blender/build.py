"""Build a Raphael VRM from a base model by running the step scripts in order.

    X:\\Blender\\blender.exe -b --factory-startup --python spikes/vrm/blender/build.py -- NAME STEPS [BASE.vrm]

STEPS is a comma list of: recolour, halo, robe, chibi, expressions. Examples:
    -- raphael_serious recolour,halo,robe,expressions
    -- raphael_chibi   recolour,halo,robe,chibi,expressions
Writes <data>\\3d\\blend\\NAME.blend and <data>\\3d\\export\\NAME.vrm (paths in rlib.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import rlib  # noqa: E402
import s1_recolour  # noqa: E402
import s2_halo_orb  # noqa: E402

a = rlib.args()
name, steps = a[0], a[1].split(",")
rlib.load_vrm(a[2] if len(a) > 2 else rlib.BASE)
chibi = "chibi" in steps
for step in steps:
    if step == "recolour":
        s1_recolour.run()
    elif step == "halo":
        # the chibi's halo is smaller relative to the (bigger) head and dim; the orb sits lower
        s2_halo_orb.run(dim=chibi)
    elif step == "robe":
        import s3_robe
        s3_robe.run()
    elif step == "chibi":  # run before robe, so the robe is fitted to her chibi body
        import s4_chibi
        s4_chibi.run()
    elif step == "expressions":
        import s5_expressions
        s5_expressions.run(chibi=chibi)
    else:
        raise SystemExit(f"unknown step {step}")
rlib.export(name)
