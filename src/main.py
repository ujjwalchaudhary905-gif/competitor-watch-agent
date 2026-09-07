"""CLI entry point — run the full competitor-watch pipeline once."""

from src.agent import run_pipeline


def main() -> None:
    print("=" * 70)
    print("Competitor Watch Agent — starting run")
    print("=" * 70)
    final_report = run_pipeline()
    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)
    print(final_report)


if __name__ == "__main__":
    main()
