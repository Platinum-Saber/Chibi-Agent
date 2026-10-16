import argparse
import asyncio
import logging
import os
import sys

from chibi_shared import config, paths

from .env import configure


def main() -> None:
    ap = argparse.ArgumentParser(prog="chibi_voice")
    ap.add_argument("--selftest", action="store_true",
                    help="speak a clip and an F5 sentence, transcribe 3 s of mic audio, print timings")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    vcfg = config.load().get("voice", {})
    configure(vcfg)
    paths.ensure()
    if args.selftest:
        from .selftest import selftest
        asyncio.run(selftest(vcfg))
    else:
        from .main import run
        asyncio.run(run(vcfg))
    sys.stdout.flush()
    # Don't wait for a model call still running on a pool thread.
    os._exit(0)


if __name__ == "__main__":
    main()
