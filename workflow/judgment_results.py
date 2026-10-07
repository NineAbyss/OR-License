

def summarize_judgments(rows):
    service_error = any(row.get("review_service_error") is True for row in rows)
    success = None if service_error else bool(rows) and all(row["validity"] for row in rows)
    result = {"success": success, "results": rows, "total_cases": len(rows),
              "valid_cases": None if service_error else sum(bool(row["validity"]) for row in rows),
              "mean_cost": sum(row["cost"] for row in rows) / len(rows) if success else None}
    if service_error:
        result.update(review_service_error=True, review_service_status="error")
    return result


def judgment_rewards(evaluation):
    if evaluation.get("review_service_error") is True:
        return {"review_service_error": 1, "total_cases": evaluation["total_cases"]}
    rewards = {"reward": float(evaluation["success"]), "valid_cases": evaluation["valid_cases"],
               "total_cases": evaluation["total_cases"]}
    if evaluation["success"]:
        rewards["mean_cost"] = evaluation["mean_cost"]
    return rewards
