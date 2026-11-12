#!/usr/bin/env python3
"""Monthly cost arithmetic for hosting options, from prices the agent read elsewhere.

What it does: reads one JSON document on stdin, adds up each option's monthly items and
burst (hourly) items, prints each option's lines and total, the difference between every
pair of options, and for a burst item with an always-on price the break-even hours.
What it never does: look up a price, guess a missing number, round a total silently or
touch the network or the disk. On a missing, negative or non-numeric number it refuses
with one line on stderr, exit code 2, and prints no total.
A burst item's monthly_cap: the cap protects one long-lived machine; servers created per
run are billed in total. So the cap limits the month only with "one_machine": true, and
otherwise limits each run.

Usage: python estimate_cost.py < options.json
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

HELP = """\
Input (JSON on stdin):
  {"currency": "<code or word, printed as given>",
   "options": [
     {"name": "<option name>",
      "items": [
        {"label": "<text>", "monthly": <number>},
        {"label": "<text>", "hourly": <number>, "hours": <number>, "runs": <number>,
         "overhead_hours": <number, optional, default 0>,
         "monthly_cap": <number or null, optional>,
         "one_machine": <true or false, optional, default false>,
         "always_on_monthly": <number, optional>}
      ]}
   ]}

A monthly item costs its "monthly" amount. A burst item is billed per hour:
  billed hours per month = (hours + overhead_hours) * runs
  one run = hourly * (hours + overhead_hours)
where "hours" is the working time of one run, "runs" the number of runs in a month and
"overhead_hours" the extra billed time of one run (start, setup, teardown).
monthly_cap: the cap protects one long-lived machine; servers created per run are billed
in total. With "one_machine": true (the same machine is kept and reused for every run)
  monthly = one run * runs, limited to monthly_cap
and otherwise (each run creates a new server, which has its own cap)
  monthly = (one run, limited to monthly_cap) * runs
With "always_on_monthly" (the monthly price of keeping the same capacity on all month)
the line also shows the break-even hours: the billed hours per month at which both cost
the same. With "one_machine" and a cap below the always-on price there is none: the
break-even hours are null and "break_even_note" says so. When each run is capped the
break-even hours are null too: the cost no longer follows the billed hours, so compare the
monthly amounts. "hourly", "hours" and "runs" must be greater than zero; every other number
must be zero or more and below a thousand million million.

Output: one JSON object. Amounts are strings with two decimals, rounded half up per
line; totals and differences add up the rounded lines, so they check out on paper.
Exit codes: 0 printed, 2 refused (one line on stderr, nothing on stdout).
Needs Python 3.9 or newer, standard library only.
"""

CENT = Decimal("0.01")
NUMBER_KINDS = (int, Decimal)
LIMIT = Decimal(10) ** 15  # far above any monthly figure; keeps every result exact at the precision used
PRECISION = 60


class Refusal(Exception):
    """The input cannot be priced; .text says why, in one line."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


class Parser(argparse.ArgumentParser):
    """argparse that reports a usage error as one line on stderr and exits 2."""

    def error(self, message):
        _fail(f"usage: {message} (see --help)")
        sys.exit(2)


def _money(value: Decimal) -> str:
    rounded = value.quantize(CENT, rounding=ROUND_HALF_UP)
    return str(abs(rounded) if rounded == 0 else rounded)  # never "-0.00"


def _kind(value) -> str:
    """The JSON type of a value, named without printing the value itself."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true or false"
    return {str: "a string", list: "a list", dict: "an object"}.get(type(value), "an unknown value")


def _number(item: dict, key: str, where: str, *, required: bool = True, positive: bool = False,
            nullable: bool = False) -> Decimal | None:
    if key not in item or (nullable and item[key] is None):
        if required:
            raise Refusal(f"{where}: '{key}' is missing")
        return None
    value = item[key]
    if isinstance(value, bool) or not isinstance(value, NUMBER_KINDS):
        raise Refusal(f"{where}: '{key}' must be a number, got {_kind(value)}")
    value = Decimal(value)
    if not value.is_finite():
        raise Refusal(f"{where}: '{key}' must be a finite number")
    if value < 0:
        raise Refusal(f"{where}: '{key}' must not be negative")
    if value >= LIMIT:
        raise Refusal(f"{where}: '{key}' is too large to be a price or a quantity")
    if positive and value == 0:
        raise Refusal(f"{where}: '{key}' must be greater than zero")
    return abs(value)  # turns a "-0.0" input into 0


def _text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise Refusal(f"{where}: '{key}' must be a non-empty string")
    return value


def _line(item, where: str) -> tuple[dict, Decimal]:
    if not isinstance(item, dict):
        raise Refusal(f"{where}: an item must be an object")
    label = _text(item, "label", where)
    where = f"{where} ('{label}')"
    has_monthly, has_hourly = "monthly" in item, "hourly" in item
    if has_monthly == has_hourly:
        raise Refusal(f"{where}: give either 'monthly' or 'hourly' with 'hours' and 'runs'")
    if has_monthly:
        monthly = _number(item, "monthly", where).quantize(CENT, rounding=ROUND_HALF_UP)
        return {"label": label, "kind": "monthly", "monthly": _money(monthly)}, monthly

    hourly = _number(item, "hourly", where, positive=True)
    hours = _number(item, "hours", where, positive=True)
    runs = _number(item, "runs", where, positive=True)
    overhead = _number(item, "overhead_hours", where, required=False) or Decimal(0)
    cap = _number(item, "monthly_cap", where, required=False, nullable=True)
    always_on = _number(item, "always_on_monthly", where, required=False)
    one_machine = item.get("one_machine", False)
    if not isinstance(one_machine, bool):
        raise Refusal(f"{where}: 'one_machine' must be true or false, got {_kind(one_machine)}")

    billed_hours = (hours + overhead) * runs
    one_run = hourly * (hours + overhead)
    uncapped = one_run * runs
    if cap is None:
        capped, amount = False, uncapped
    elif one_machine:
        capped, amount = uncapped > cap, min(uncapped, cap)
    else:
        capped, amount = one_run > cap, min(one_run, cap) * runs
    monthly = amount.quantize(CENT, rounding=ROUND_HALF_UP)
    line = {"label": label, "kind": "burst", "hourly": str(hourly), "hours": str(hours), "runs": str(runs),
            "overhead_hours": str(overhead), "billed_hours_per_month": _money(billed_hours),
            "uncapped_monthly": _money(uncapped), "monthly_cap": None if cap is None else _money(cap),
            "one_machine": one_machine, "cap_applies_to": None if cap is None else
            ("the month of one machine" if one_machine else "each run"),
            "capped": capped, "monthly": _money(monthly)}
    if always_on is not None:
        line["always_on_monthly"] = _money(always_on)
        if one_machine and cap is not None and cap < always_on:
            line["break_even_hours_per_month"] = None
            line["break_even_note"] = "with the cap, this item never reaches the always-on price"
        elif capped and not one_machine:
            line["break_even_hours_per_month"] = None
            line["break_even_note"] = ("each run is capped, so the cost no longer follows the billed hours; "
                                       "compare the monthly amounts")
        else:
            line["break_even_hours_per_month"] = _money(always_on / hourly)
        line["cheaper_than_always_on"] = monthly < always_on
    return line, monthly


def estimate(doc) -> dict:
    if not isinstance(doc, dict):
        raise Refusal("input must be a JSON object with 'currency' and 'options'")
    currency = _text(doc, "currency", "input")
    options = doc.get("options")
    if not isinstance(options, list) or not options:
        raise Refusal("input: 'options' must be a non-empty list")
    out, totals = [], []
    for i, option in enumerate(options, 1):
        where = f"option {i}"
        if not isinstance(option, dict):
            raise Refusal(f"{where}: an option must be an object")
        name = _text(option, "name", where)
        where = f"option '{name}'"
        items = option.get("items")
        if not isinstance(items, list) or not items:
            raise Refusal(f"{where}: 'items' must be a non-empty list")
        lines, total = [], Decimal(0)
        for j, item in enumerate(items, 1):
            line, amount = _line(item, f"{where} item {j}")
            lines.append(line)
            total += amount
        out.append({"name": name, "lines": lines, "total": _money(total)})
        totals.append((name, total))
    if len({n for n, _ in totals}) != len(totals):
        raise Refusal("input: option names must be different from each other")

    differences = []
    for a in range(len(totals)):
        for b in range(a + 1, len(totals)):
            (na, ta), (nb, tb) = totals[a], totals[b]
            differences.append({"between": [na, nb], "difference": _money(abs(ta - tb)),
                                "cheaper": None if ta == tb else (na if ta < tb else nb)})
    lowest = min(t for _, t in totals)
    cheapest = [n for n, t in totals if t == lowest]
    return {"currency": currency, "period": "month", "options": out,
            "cheapest": cheapest[0] if len(cheapest) == 1 else None, "differences": differences}


def _reject_constant(name: str):
    raise Refusal(f"input: {name} is not a number")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(
        prog="estimate_cost.py", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Add up monthly costs of hosting options from a JSON document read on stdin.",
        epilog=HELP)
    parser.parse_args(argv)
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            raise Refusal("no input: pipe a JSON document on stdin (see --help)")
        try:
            doc = json.loads(raw, parse_float=Decimal, parse_constant=_reject_constant)
        except json.JSONDecodeError as exc:
            raise Refusal(f"input is not valid JSON: {exc.msg} at line {exc.lineno} column {exc.colno}") from None
        except ValueError:
            # Python refuses to convert an integer literal of thousands of digits.
            raise Refusal("input holds a number too long to read") from None
        with localcontext() as ctx:
            ctx.prec = PRECISION
            result = estimate(doc)
    except Refusal as refusal:
        _fail(f"refused: {refusal.text}")
        return 2
    except (InvalidOperation, RecursionError, UnicodeDecodeError) as exc:
        _fail(f"refused: input could not be read ({type(exc).__name__})")
        return 2
    print(json.dumps(result, indent=2))
    return 0


def _fail(message: str) -> None:
    print(" ".join(message.split()), file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
