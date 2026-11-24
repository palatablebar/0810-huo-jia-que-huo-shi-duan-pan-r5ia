from app.business import decision


def policy(result):
    return decision(
        result, "SERVICE_LIMIT" if result["flag"] else None, upper_bound=True
    )
