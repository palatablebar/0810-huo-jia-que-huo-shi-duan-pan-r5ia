from app.business import measured, overlap


def compute(data):
    window, empty, limit = data
    selling = sum(b - a for a, b in window)
    unavailable = overlap(window, empty)
    rate = (unavailable * 20000 + selling) // (2 * selling)
    return measured(
        rate,
        limit,
        "基点",
        {"selling_min": selling, "stockout_min": unavailable},
        unavailable * 10000 > limit * selling,
    )
