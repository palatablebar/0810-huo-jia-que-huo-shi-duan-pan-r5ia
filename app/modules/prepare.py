from app.business import DomainIssue, by_kind, prepared, single, intervals, subtract


def prepare(rows):
    def extract(kind):
        spans = [(r["start_min"], r["end_min"]) for r in by_kind(rows, kind)]
        if any(a >= b for a, b in spans):
            raise DomainIssue("BAD_INTERVAL")
        return intervals(spans)

    window = subtract(extract("open"), extract("blackout"))
    if not window:
        raise DomainIssue("NO_SELLING_TIME")
    limit = single(rows, "target")["limit_bp"]
    if limit > 10000:
        raise DomainIssue("BAD_RATE_LIMIT")
    return prepared(
        len(window),
        {"selling_min": sum(b - a for a, b in window)},
        (window, extract("empty"), limit),
    )
