#!/usr/bin/env python3
"""Deterministic tests for cfg_context. Run: python test_cfg_context.py"""

import cfg as C


def ins(addr, mnem, dest=None, reloc=False, size=4):
    """Build one objdiff-shaped instruction entry. address is omitted when 0,
    mirroring objdiff's serialization (see parse_instructions)."""
    parts = [{"opcode": {"mnemonic": mnem}}]
    if dest is not None:
        parts.append({"arg": {"branch_dest": str(dest)}})
    elif reloc:
        parts.append({"arg": {"reloc": True}})
    inner = {"size": size,
             "formatted": f"{mnem} 0x{dest:x}" if dest is not None else mnem,
             "parts": parts}
    if addr != 0:  # objdiff omits address==0
        inner["address"] = str(addr)
    return {"instruction": inner}


def sym(name, entries, size):
    return {"name": name, "size": str(size), "match_percent": 100.0, "instructions": entries}


def cfg_of(entries):
    return C.build_cfg(C.parse_instructions({"instructions": entries}))


# --- classification (the tripwire: mflr/mtctr/mtlr must NOT read as branches) ---

def test_classify():
    assert C.classify("mflr", False, False) == C.LINEAR
    assert C.classify("mtlr", False, False) == C.LINEAR
    assert C.classify("mtctr", False, False) == C.LINEAR
    assert C.classify("bl", False, True) == C.CALL
    assert C.classify("blrl", False, False) == C.CALL
    assert C.classify("bctrl", False, False) == C.CALL
    assert C.classify("blr", False, False) == C.RET
    assert C.classify("bctr", False, False) == C.INDIRECT
    assert C.classify("b", False, True) == C.TAILCALL
    assert C.classify("b", True, False) == C.JUMP
    assert C.classify("beq", True, False) == C.CONDBR
    assert C.classify("bdnz", True, False) == C.CONDBR
    assert C.classify("ble+", True, False) == C.CONDBR   # hint suffix stripped
    assert C.classify("beqlr", False, False) == C.CONDRET
    print("ok classify")


# --- Case 1: linear -------------------------------------------------------------

def test_linear():
    cfg = cfg_of([ins(0, "lwz"), ins(4, "addi"), ins(8, "stw")])
    assert len(cfg.blocks) == 1
    assert cfg.blocks[0].succ == []
    assert cfg.loop_headers == {}
    assert cfg.n_conds == 0
    print("ok linear")


# --- Case 2: bdnz counter loop --------------------------------------------------

def test_loop_bdnz():
    cfg = cfg_of([
        ins(0, "li"),
        ins(4, "add"),          # loop body start (branch target)
        ins(8, "bdnz", dest=4),
        ins(12, "blr"),
    ])
    assert len(cfg.blocks) == 3, [b.start for b in cfg.blocks]
    assert cfg.n_conds == 1
    # the block containing bdnz loops back to the body block
    body = next(b for b in cfg.blocks if b.start == 4)
    assert body.bid in cfg.loop_headers, cfg.loop_headers
    assert body.succ[0] == body.bid  # back-edge to itself (single-block body)
    # exit block ends in blr
    assert cfg.blocks[-1].succ == []
    print("ok loop_bdnz")


# --- Case 3: bctr switch dispatch ----------------------------------------------

def test_switch_bctr():
    cfg = cfg_of([
        ins(0, "cmplwi"),
        ins(4, "bgt", dest=16),   # -> default block
        ins(8, "mtctr"),          # not a branch: must stay in same block as bctr
        ins(12, "bctr"),          # indirect -> partial
        ins(16, "li"),            # default
        ins(20, "blr"),
    ])
    assert len(cfg.blocks) == 3, [b.start for b in cfg.blocks]
    assert cfg.n_conds == 1
    assert cfg.loop_headers == {}
    # mtctr+bctr share a block, which is a partial indirect exit
    disp = next(b for b in cfg.blocks if b.start == 8)
    assert disp.succ == []
    assert any("indirect" in n for n in cfg.notes), cfg.notes
    assert not any("mtctr" in n for n in cfg.notes)  # mtctr must not be flagged
    print("ok switch_bctr")


# --- render smoke ---------------------------------------------------------------

def test_render():
    data = {"left": {"symbols": [sym("f", [ins(0, "li"), ins(4, "add"),
                                           ins(8, "bdnz", dest=4), ins(12, "blr")], 16)]}}
    out = C.context_for(data, "u/x", "f")
    assert "[FUNC] f" in out and "[CFG]" in out and "LOOP" in out and "[LOOPS]" in out
    print("ok render")


if __name__ == "__main__":
    test_classify()
    test_linear()
    test_loop_bdnz()
    test_switch_bctr()
    test_render()
    print("ALL PASS")
