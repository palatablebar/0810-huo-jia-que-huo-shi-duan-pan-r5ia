EXPECTED = {
    "0001": (2, 6429, "READY"),
    "0002": (1, 200, "READY"),
    "0003": (0, None, "NO_SELLING_TIME"),
    "0004": (1, 5000, "SERVICE_LIMIT"),
}
EVIDENCE = {
    "0001": {"selling_min": 70, "stockout_min": 45},
    "0002": {"selling_min": 50, "stockout_min": 1},
}
