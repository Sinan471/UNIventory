
class EvaluationService:

    @staticmethod
    def classification_accuracy(actual, predicted):
        if not actual or len(actual) != len(predicted):
            return {
                "accuracy": None,
                "status": "NOT_APPLICABLE",
                "total": 0,
            }

        correct = sum(
            1 for a, p in zip(actual, predicted) if a == p
        )

        return {
            "accuracy": round(correct / len(actual) * 100, 2),
            "correct": correct,
            "total": len(actual),
            "status": "COMPLETED",
        }

    @staticmethod
    def matching_usefulness(results, useful_listing_ids):
        if not results:
            return {
                "useful_matches": 0,
                "total": 0,
                "usefulness_rate": None,
                "status": "NOT_APPLICABLE",
            }

        useful_ids = set(useful_listing_ids)

        useful_count = sum(
            1 for item in results[:3]
            if item.get("listing_id") in useful_ids
        )

        return {
            "useful_matches": useful_count,
            "total": min(len(results), 3),
            "usefulness_rate": round(
                useful_count / min(len(results), 3) * 100, 2
            ),
            "status": "COMPLETED",
        }

    @staticmethod
    def compare_classic_vs_ai(classic_results, ai_results, useful_ids):
        classic = EvaluationService.matching_usefulness(
            classic_results, useful_ids
        )

        ai = EvaluationService.matching_usefulness(
            ai_results, useful_ids
        )

        return {
            "classic": classic,
            "ai": ai,
            "improvement": (
                None
                if classic["usefulness_rate"] is None
                or ai["usefulness_rate"] is None
                else round(
                    ai["usefulness_rate"]
                    - classic["usefulness_rate"],
                    2,
                )
            ),
        }

