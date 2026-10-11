"""Run production and tooling tests together, including the 30-second budget."""
import argparse
from pathlib import Path
import sys
import time
import unittest
import io
from concurrent.futures import ProcessPoolExecutor

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def tooling_tests():
    # Separate process: tooling tests patch evaluator methods and must not
    # change the production suite's runtime while both suites run.
    suite=unittest.TestLoader().discover(str(ROOT/'scripts/perception/tests'),top_level_dir=str(ROOT))
    output=io.StringIO()
    result=unittest.TextTestRunner(stream=output,verbosity=1).run(suite)
    return result.testsRun,result.wasSuccessful(),output.getvalue()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-seconds',type=float,default=30)
    args=parser.parse_args()
    started=time.perf_counter()
    with ProcessPoolExecutor(max_workers=1) as pool:
        tooling=pool.submit(tooling_tests)
        suite=unittest.TestLoader().discover(str(ROOT/'tests'),top_level_dir=str(ROOT))
        result=unittest.TextTestRunner(verbosity=1).run(suite)
        tool_count,tool_passed,tool_log=tooling.result()
    print(tool_log,file=sys.stderr,end='')
    elapsed=time.perf_counter()-started
    within_budget=elapsed<=args.max_seconds
    print(f'All {result.testsRun+tool_count} tests: {elapsed:.3f}s; '
          f'budget {args.max_seconds:g}s: {"PASS" if within_budget else "FAIL"}',flush=True)
    return 0 if result.wasSuccessful() and tool_passed and within_budget else 1


if __name__=='__main__':sys.exit(main())
