"""Cash and time-weighted value bookkeeping shared by the single-sleeve engines and the shared-account ledger."""
from __future__ import annotations


class CashBox:
    """A mutable cash balance. One engine alone owns its box; in the paper ledger every sleeve holds the SAME box."""

    def __init__(self, value: float):
        self.value = float(value)


class Nav:
    """Time-weighted value and deposits.

    `mark(cash, invested, deposit_day)` is called once per session after the day's fills. With a contribution, a deposit
    is added to the cash box on `deposit_day` AFTER the day is marked, so it is not a return and is in the book when the
    close's orders are sized. Without one, `nav` is just the account value (the old single `equity` curve).
    Returns (nav, value, deposited): `value` is real money including the deposit.
    """

    def __init__(self, capital: float, contribution: float = 0.0):
        self.contribution = contribution
        self.nav = self.prev_value = self.deposited = float(capital)

    def mark(self, cash: CashBox, invested: float, deposit_day: bool) -> tuple[float, float, float]:
        pre = cash.value + invested  # value before today's deposit
        if self.contribution:
            self.nav *= pre / self.prev_value if self.prev_value > 0 else 1.0
            if deposit_day:
                cash.value += self.contribution
                self.deposited += self.contribution
        else:
            self.nav = pre
        value = cash.value + invested
        self.prev_value = value
        return self.nav, value, self.deposited
