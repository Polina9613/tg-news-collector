"""
Анализирует логи systemd (или локальный лог-файл) на предмет расхода токенов.
Группирует по методам LLM, считает суммарный и средний расход,
находит самые дорогие вызовы.

Использование:
  python scripts/token_audit.py --since "2026-07-01" --until "2026-07-02"
  python scripts/token_audit.py --log-file /path/to/log.txt
"""
import argparse
import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class TokenStats:
    calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    max_single_call: int = 0

    @property
    def avg_tokens(self) -> float:
        return self.total_tokens / self.calls if self.calls else 0


def parse_journalctl_logs(since: str, until: str | None = None) -> list[str]:
    """Получает логи из journalctl за период."""
    cmd = ["journalctl", "-u", "tg-news", "--since", since, "--no-pager"]
    if until:
        cmd += ["--until", until]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.splitlines()


def parse_log_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return f.readlines()


def analyze_lines(lines: list[str]) -> dict:
    """
    Парсит строки логов вида:
    [tokens] prompt=100 completion=50 total=150
    [LLM input] check_relevance: 1200 chars (~300 tokens)
    """
    by_method: dict[str, TokenStats] = defaultdict(TokenStats)
    current_method = "unknown"

    total_calls = 0
    total_tokens_all = 0
    enrich_cycles = 0
    digest_runs = 0

    token_pattern = re.compile(r"\[tokens?\].*prompt=(\d+).*completion=(\d+).*total=(\d+)")
    input_pattern = re.compile(r"\[LLM input\]\s+(\w+):\s+(\d+)\s+chars")
    enricher_line = re.compile(r"llm\.enricher.*\[(\d+)/(\d+)\]")
    digest_line = re.compile(r"digest\.generator|llm_digest")

    for line in lines:
        input_match = input_pattern.search(line)
        if input_match:
            current_method = input_match.group(1)

        token_match = token_pattern.search(line)
        if token_match:
            p, c, t = map(int, token_match.groups())
            stats = by_method[current_method]
            stats.calls += 1
            stats.prompt_tokens += p
            stats.completion_tokens += c
            stats.total_tokens += t
            stats.max_single_call = max(stats.max_single_call, t)
            total_calls += 1
            total_tokens_all += t

        if enricher_line.search(line):
            enrich_cycles += 1

        if digest_line.search(line):
            digest_runs += 1

    return {
        "by_method": dict(by_method),
        "total_calls": total_calls,
        "total_tokens": total_tokens_all,
        "enrich_cycle_lines": enrich_cycles,
        "digest_related_lines": digest_runs,
    }


def print_report(analysis: dict) -> None:
    print("\n" + "═" * 70)
    print("  АУДИТ РАСХОДА ТОКЕНОВ")
    print("═" * 70)

    by_method = analysis["by_method"]
    if not by_method:
        print("\n⚠️  Токены в логах не найдены.")
        print("   Убедись что включено логирование [tokens] в LLM-провайдере")
        print("   и что уровень логирования DEBUG (не INFO).")
        return

    print(f"\n  Всего LLM-вызовов: {analysis['total_calls']}")
    print(f"  Всего токенов: {analysis['total_tokens']:,}")
    if analysis["total_calls"]:
        print(f"  Средний расход на вызов: {analysis['total_tokens'] // analysis['total_calls']:,}")

    print(f"\n  {'Метод':<30} {'Вызовов':>8} {'Всего токенов':>14} {'Среднее':>10} {'Макс':>8}")
    print("  " + "─" * 72)

    sorted_methods = sorted(by_method.items(), key=lambda x: -x[1].total_tokens)
    for method, stats in sorted_methods:
        pct = (stats.total_tokens / analysis["total_tokens"] * 100) if analysis["total_tokens"] else 0
        print(
            f"  {method:<30} {stats.calls:>8} {stats.total_tokens:>14,} "
            f"{stats.avg_tokens:>10,.0f} {stats.max_single_call:>8,}  ({pct:.0f}%)"
        )

    print("\n" + "═" * 70)
    print("  РЕКОМЕНДАЦИИ")
    print("═" * 70)

    top_method = sorted_methods[0] if sorted_methods else None
    if top_method:
        name, stats = top_method
        pct = (stats.total_tokens / analysis["total_tokens"] * 100) if analysis["total_tokens"] else 0
        print(f"\n  🔴 Самый дорогой метод: {name} — {pct:.0f}% всех токенов")
        if stats.avg_tokens > 1500:
            print(f"     Средний расход {stats.avg_tokens:.0f} токенов на вызов — подозрительно много.")
            print(f"     Проверь длину промпта и обрезку входного текста.")

    if "generate_summary" in by_method:
        gs = by_method["generate_summary"]
        print(f"\n  💡 generate_summary: {gs.calls} вызовов, {gs.total_tokens:,} токенов")
        print(f"     Это резюме для Excel — не используется в дайджесте.")
        print(f"     Можно убрать из автопайплайна → экономия {gs.total_tokens:,} токенов")

    if "check_relevance" in by_method and "classify_post" in by_method:
        cr = by_method["check_relevance"].total_tokens
        cp = by_method["classify_post"].total_tokens
        print(f"\n  💡 check_relevance + classify_post: {cr + cp:,} токенов суммарно")
        print(f"     Объединение в 1 вызов сэкономит ~{int((cr + cp) * 0.3):,} токенов")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Аудит расхода токенов LLM")
    parser.add_argument("--since", default="1 day ago", help="С какого времени (для journalctl)")
    parser.add_argument("--until", default=None, help="До какого времени")
    parser.add_argument("--log-file", default=None, help="Путь к файлу логов вместо journalctl")
    args = parser.parse_args()

    if args.log_file:
        lines = parse_log_file(args.log_file)
    else:
        lines = parse_journalctl_logs(args.since, args.until)

    analysis = analyze_lines(lines)
    print_report(analysis)
