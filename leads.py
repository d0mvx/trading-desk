"""Lead IDs (2026-10-20 21:1x, research upgrade): one stable ID per coin = 'L' + first 6 chars of the mint. Deterministic
(no state file, no locking), so scan -> judge/RugCheck -> buy -> exits -> shadow book all carry the same ID and one coin's
whole life can be traced with:  grep -h L<id> logs/*.log logs/*.jsonl scan/*.jsonl"""
def lead_id(mint):
    return ("L" + str(mint)[:6]) if mint else None
def ltag(mint):
    l = lead_id(mint); return f"[{l}] " if l else ""
