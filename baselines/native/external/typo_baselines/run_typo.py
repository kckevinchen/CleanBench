"""Published CleanBench inference bridge; see baselines/provenance.json."""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[A-Za-z']+")


HAS_ALPHA = re.compile(r"[A-Za-z]")


Cell = tuple[str, int, int]  # (dataset, row, col)


def build_symspell(max_edit_distance: int):
    import importlib.resources as ir

    from symspellpy import SymSpell

    sym = SymSpell(max_dictionary_edit_distance=max_edit_distance, prefix_length=7)
    dict_path = ir.files("symspellpy") / "frequency_dictionary_en_82_765.txt"
    sym.load_dictionary(str(dict_path), term_index=0, count_index=1)
    return sym


def symspell_correct(value: str, sym, args):
    """Return ``(flagged, corrected)``.

    ``flagged`` matches ``symspell_flag`` exactly (detection is unchanged).
    ``corrected`` is the token-substituted string when a strictly-closer real word
    exists for at least one token, else ``None`` (flagged-but-uncorrectable, e.g.
    ``flag_unknown`` firing on an out-of-dictionary token with no near word).
    """
    from symspellpy import Verbosity

    if not HAS_ALPHA.search(value):
        return (False, None)
    flagged = False
    changed = False

    def _sub(m):
        nonlocal flagged, changed
        tok = m.group(0)
        if len(tok) < args.min_token_len:
            return tok
        if args.skip_allcaps and tok.isupper() and len(tok) > 1:
            return tok
        low = tok.lower()
        sugg = sym.lookup(
            low, Verbosity.CLOSEST, max_edit_distance=args.max_edit_distance, include_unknown=False
        )
        if not sugg:
            if args.flag_unknown:
                flagged = True
            return tok
        if sugg[0].distance == 0:
            return tok
        flagged = True
        repl = sugg[0].term
        if tok.isupper():
            repl = repl.upper()
        elif tok[:1].isupper():
            repl = repl.capitalize()
        changed = True
        return repl

    corrected = TOKEN_RE.sub(_sub, value)
    return (flagged, corrected if changed else None)


def symspell_flag(value: str, sym, args) -> bool:
    """True if any token has a strictly-closer dictionary word (=> misspelled)."""
    return symspell_correct(value, sym, args)[0]


def run_symspell(cells: list[tuple[Cell, str]], args) -> dict[Cell, str | None]:
    sym = build_symspell(args.max_edit_distance)
    out: dict[Cell, str | None] = {}
    for key, val in cells:
        flagged, corrected = symspell_correct(val, sym, args)
        if flagged:
            out[key] = corrected
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def run_neuspell(cells: list[tuple[Cell, str]], args) -> dict[Cell, str | None]:
    import neuspell
    import torch

    # NeuSpell's checkpoints predate torch 2.6, whose torch.load default flipped to
    # weights_only=True and rejects them ("Unsupported operand"). Force the legacy
    # behavior for this trusted, just-downloaded checkpoint. Also load the BERT
    # state_dict non-strictly: old checkpoints carry an extra
    # ``embeddings.position_ids`` buffer that newer transformers no longer expect.
    _orig_load = torch.load
    _orig_load_sd = torch.nn.Module.load_state_dict

    def _compat_load(*a, **k):
        k.setdefault("weights_only", False)
        return _orig_load(*a, **k)

    def _compat_load_sd(self, state_dict, strict=True, **k):
        return _orig_load_sd(self, state_dict, strict=False, **k)

    torch.load = _compat_load
    torch.nn.Module.load_state_dict = _compat_load_sd
    try:
        checker_cls = getattr(neuspell, args.neuspell_checker)
        checker = checker_cls()
        checker.from_pretrained()
    finally:
        torch.load = _orig_load
        torch.nn.Module.load_state_dict = _orig_load_sd

    # Only score cells with alphabetic content; batch for speed.
    idx = [i for i, (_, v) in enumerate(cells) if HAS_ALPHA.search(v)]
    strings = [cells[i][1] for i in idx]
    flagged: dict[Cell, str | None] = {}
    B = args.neuspell_batch
    for start in range(0, len(strings), B):
        batch = strings[start : start + B]
        try:
            corrected = checker.correct_strings(batch)
        except Exception as e:  # noqa: BLE001
            print(f"[neuspell] batch {start} failed: {e}")
            continue
        for k, corr in enumerate(corrected):
            orig = batch[k]
            if _norm(corr) != _norm(orig):
                flagged[cells[idx[start + k]][0]] = corr
    return flagged
