#!/usr/bin/env python3
"""
Structured control-flow context for the matching harness (HELIOS-style, layer 1).

Given the TARGET assembly of a PowerPC (Gekko) function -- as produced by
`objdiff-cli diff ... --format json` -- build a compact basic-block / CFG map and
render it as a few lines of text. The worker (Claude) receives the control-flow
skeleton already chewed instead of having to infer loops and branches from linear
asm, which attacks "structural blindness" (mis-reconstructed control flow).

This module is a PURE library: it takes already-parsed objdiff JSON and returns
text. It never normalizes instructions to an IR (unlike HELIOS): the raw PPC detail
is exactly what byte-matching needs, so the map sits ON TOP of the asm, it does not
replace it. See harness/docs/plan_structured_context.md (Anexo A) for the data
contract this relies on.

CLI (worker-facing, mirrors tools/decomp-diff.py):
    python tools/cfg.py -u <unit> -d <symbol> [--asm]

Root (where build/tools/objdiff-cli lives) is auto-detected as the parent of tools/,
overridable with $SMS_ROOT.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional

# --- Control-flow classification of PPC branch mnemonics (see Anexo A.3) --------

# Instruction kinds, by their effect on the CFG.
JUMP = "jump"        # unconditional local jump `b <dest>`          -> [target]
TAILCALL = "tail"    # `b <reloc>` to another function              -> [] (leaves)
RET = "ret"          # `blr`                                        -> []
INDIRECT = "indir"   # `bctr` switch/vtable dispatch                -> [] + partial note
CONDBR = "condbr"    # `beq/bne/.../bdnz` with branch_dest          -> [target, fallthrough]
CONDRET = "condret"  # `beqlr/bnelr/...` conditional return to LR   -> [fallthrough] + note
CALL = "call"        # `bl`, `blrl`, `bctrl` (link variants)        -> does NOT end a block
LINEAR = "linear"    # anything else                               -> does NOT end a block

# Kinds that terminate a basic block.
TERMINATORS = {JUMP, TAILCALL, RET, INDIRECT, CONDBR, CONDRET}


def classify(mnemonic: str, has_branch_dest: bool, has_reloc: bool) -> str:
    """Map a mnemonic (+ its arg kind) to a CFG effect. Hint suffixes +/- stripped."""
    m = mnemonic.rstrip("+-")
    if not m.startswith("b"):
        return LINEAR  # every PPC control transfer starts with 'b' (mflr/mtctr/... are not)
    if m == "bl" or m in ("blrl", "bctrl"):
        return CALL
    if m == "blr":
        return RET
    if m == "bctr":
        return INDIRECT
    if m == "b":
        return TAILCALL if has_reloc else JUMP
    if m.endswith("lr"):          # beqlr, bnelr, bgelr, ... conditional return
        return CONDRET
    if m.endswith("ctr"):         # rare conditional indirect
        return INDIRECT
    if m.startswith("b") and has_branch_dest:  # beq, bne, bge, ble, blt, bgt, bdnz, bdz
        return CONDBR
    return LINEAR


# --- Parsing objdiff JSON -------------------------------------------------------

@dataclass
class Inst:
    addr: int            # section-relative absolute address
    size: int
    text: str            # `formatted` string, e.g. "beq 0x1140"
    mnemonic: str
    kind: str
    dest: Optional[int]  # branch target (section-relative), if a local branch


def parse_instructions(symbol: dict) -> list[Inst]:
    """Extract the instruction stream of one `left` (target) symbol."""
    out: list[Inst] = []
    for entry in symbol.get("instructions") or []:
        ins = entry.get("instruction")
        if not ins:  # diff gap rows carry no 'instruction' key
            continue
        parts = ins.get("parts") or []
        if not parts:
            continue
        mnem = (parts[0].get("opcode") or {}).get("mnemonic")
        if not mnem:
            continue
        dest = None
        has_reloc = False
        for p in parts[1:]:
            a = p.get("arg") or {}
            if "branch_dest" in a:
                dest = int(a["branch_dest"])
            elif a.get("reloc"):
                has_reloc = True
        out.append(
            Inst(
                # objdiff omits 'address' when it is 0 (first instruction of a section)
                addr=int(ins.get("address", 0)),
                size=int(ins.get("size", 4)),
                text=ins.get("formatted", mnem).rstrip(),
                mnemonic=mnem,
                kind=classify(mnem, dest is not None, has_reloc),
                dest=dest,
            )
        )
    return out


# --- CFG construction -----------------------------------------------------------

@dataclass
class Block:
    bid: int
    start: int                       # section-relative start address
    insts: list[Inst]
    succ: list[int] = field(default_factory=list)  # successor block ids
    labels: dict[int, str] = field(default_factory=dict)  # succ bid -> edge label


@dataclass
class Cfg:
    blocks: list[Block]
    loop_headers: dict[int, str]     # bid -> reason (e.g. "bdnz back-edge")
    notes: list[str]
    n_conds: int


def build_cfg(insts: list[Inst]) -> Cfg:
    if not insts:
        return Cfg([], {}, [], 0)

    addr_index = {i.addr: n for n, i in enumerate(insts)}

    # 1. leaders: first inst, branch targets, insts after a terminator.
    leaders = {insts[0].addr}
    for n, i in enumerate(insts):
        if i.dest is not None and i.dest in addr_index:
            leaders.add(i.dest)
        if i.kind in TERMINATORS and n + 1 < len(insts):
            leaders.add(insts[n + 1].addr)

    # 2. cut into blocks (ordered by address).
    starts = sorted(leaders)
    start_to_bid = {s: b for b, s in enumerate(starts)}
    blocks = [Block(b, s, []) for b, s in enumerate(starts)]
    cur = 0
    for i in insts:
        if i.addr in start_to_bid:
            cur = start_to_bid[i.addr]
        blocks[cur].insts.append(i)

    # 3. edges from each block's last instruction.
    notes: list[str] = []
    n_conds = 0
    for b in blocks:
        if not b.insts:
            continue
        last = b.insts[-1]
        nxt_addr = last.addr + last.size
        nxt_bid = start_to_bid.get(nxt_addr)
        tgt_bid = start_to_bid.get(last.dest) if last.dest is not None else None

        if last.kind == JUMP and tgt_bid is not None:
            b.succ = [tgt_bid]
            b.labels[tgt_bid] = last.mnemonic
        elif last.kind == CONDBR and tgt_bid is not None:
            n_conds += 1
            b.succ = [tgt_bid] + ([nxt_bid] if nxt_bid is not None else [])
            b.labels[tgt_bid] = last.mnemonic
            if nxt_bid is not None:
                b.labels[nxt_bid] = "fallthrough"
        elif last.kind == CONDRET:
            b.succ = [nxt_bid] if nxt_bid is not None else []
            notes.append(f"B{b.bid} ends in {last.mnemonic} -> conditional return")
        elif last.kind == INDIRECT:
            b.succ = []
            notes.append(
                f"B{b.bid} ends in {last.mnemonic} -> indirect (switch/vtable); CFG partial"
            )
        elif last.kind in (RET, TAILCALL):
            b.succ = []
        else:  # block split by a leader; last inst is not a terminator -> fallthrough
            b.succ = [nxt_bid] if nxt_bid is not None else []
            if nxt_bid is not None:
                b.labels[nxt_bid] = "fallthrough"

    # 4. loop headers: any edge to a block at a lower-or-equal start = back-edge.
    loop_headers: dict[int, str] = {}
    for b in blocks:
        for s in b.succ:
            if blocks[s].start <= b.start:
                reason = b.insts[-1].mnemonic if b.insts else "branch"
                loop_headers[s] = f"{reason} back-edge from B{b.bid}"

    return Cfg(blocks, loop_headers, notes, n_conds)


# --- Rendering ------------------------------------------------------------------

def render(meta: dict, cfg: Cfg, with_asm: bool = False) -> str:
    base = cfg.blocks[0].start if cfg.blocks else 0

    def off(addr: int) -> str:
        return f"0x{addr - base:x}"

    lines: list[str] = []
    lines.append(
        f"[FUNC] {meta['name']} @ {meta['unit']} | {meta['size']} bytes | "
        f"{len(cfg.blocks)} blocks | loops: {len(cfg.loop_headers)} | "
        f"conds: {cfg.n_conds} | fuzzy {meta['match']:.2f}%"
    )
    lines.append("[CFG]")
    for b in cfg.blocks:
        end = b.insts[-1].addr if b.insts else b.start
        rng = f"{off(b.start)}-{off(end)}"
        if b.succ:
            succ_txt = " | ".join(
                f"B{s}" + (f" ({b.labels[s]})" if b.labels.get(s) and b.labels[s] != "fallthrough" else "")
                for s in b.succ
            )
        else:
            last = b.insts[-1].mnemonic if b.insts else "?"
            succ_txt = "(exit)" if last in ("blr", "b") else f"(exit: {last})"
        head = " LOOP" if b.bid in cfg.loop_headers else ""
        lines.append(f"  B{b.bid}[{rng}]{head} -> {succ_txt}")
        if with_asm:
            for i in b.insts:
                lines.append(f"      {off(i.addr)}: {i.text}")
    if cfg.loop_headers:
        lines.append(
            "[LOOPS] " + "; ".join(f"B{h} ({r})" for h, r in sorted(cfg.loop_headers.items()))
        )
    for note in cfg.notes:
        lines.append(f"[NOTE] {note}")
    return "\n".join(lines)


# --- Convenience: find a symbol + render ---------------------------------------

def find_symbol(data: dict, name: str) -> Optional[dict]:
    for s in data.get("left", {}).get("symbols", []):
        if s.get("name") == name or s.get("demangled_name") == name:
            return s
    return None


def context_for(data: dict, unit: str, symbol_name: str, with_asm: bool = False) -> str:
    sym = find_symbol(data, symbol_name)
    if sym is None:
        return f"[cfg] symbol {symbol_name!r} not found in unit {unit!r}"
    insts = parse_instructions(sym)
    if not insts:
        return f"[cfg] {symbol_name}: no instructions (external/data symbol?)"
    cfg = build_cfg(insts)
    meta = {
        "name": sym.get("name"),
        "unit": unit,
        "size": int(sym.get("size", 0)),
        "match": float(sym.get("match_percent") or 0.0),
    }
    return render(meta, cfg, with_asm=with_asm)


def run_objdiff(unit: str, cli: str, root: str) -> dict:
    result = subprocess.run(
        [cli, "diff", "-c", "functionRelocDiffs=data_value", "-u", unit, "-o", "-", "--format", "json"],
        capture_output=True,
        cwd=root,
    )
    if result.returncode != 0:
        print(f"objdiff-cli error: {result.stderr.decode()}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def main() -> None:
    ap = argparse.ArgumentParser(description="Structured CFG context for a target function.")
    ap.add_argument("-u", "--unit", required=True)
    ap.add_argument("-d", "--symbol", required=True)
    ap.add_argument("--asm", action="store_true", help="also print raw asm per block")
    default_root = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."))
    ap.add_argument("--root", default=os.environ.get("SMS_ROOT", default_root))
    args = ap.parse_args()
    cli = os.environ.get("OBJDIFF_CLI", os.path.join(args.root, "build", "tools", "objdiff-cli"))
    data = run_objdiff(args.unit, cli, args.root)
    print(context_for(data, args.unit, args.symbol, with_asm=args.asm))


if __name__ == "__main__":
    main()
