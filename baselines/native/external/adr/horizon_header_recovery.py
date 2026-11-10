"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import io


class FDStream(io.StringIO):
    def __init__(self, text, decoded):
        super().__init__(text)
        self.decoded = decoded

    def __next__(self):
        return FDLine(super().__next__(), self.decoded)


class FDLine(str):
    def __new__(cls, value, decoded):
        line = super().__new__(cls, value)
        line.decoded = decoded
        return line

    def split(self, sep=None, maxsplit=-1):
        if sep != "⇒" or maxsplit != -1:
            raise ValueError("Native Horizon FD reader contract changed")
        fields = super().split(sep)
        if len(fields) != 2 or any(field.strip() not in self.decoded for field in fields):
            raise ValueError("Invalid encoded Horizon FD")
        return [SourceColumn(self.decoded[field.strip()]) for field in fields]


class SourceColumn(str):
    """An FD-parser field whose strip operation returns the exact source name."""

    def strip(self, chars=None):
        if chars is not None:
            raise ValueError("Unexpected native FD field stripping")
        return str(self)
