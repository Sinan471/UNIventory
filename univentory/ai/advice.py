
class ActionAdviceService:

    OPTIONS = [
        "REUSE",
        "REPAIR",
        "REFURBISH",
        "DONATE",
        "RECYCLE",
    ]

    @classmethod
    def compare_options(cls, asset):
        options = []

        if asset is None:
            return {
                "status": "INSUFFICIENT_DATA",
                "options": [],
                "reason": "Asset information is unavailable."
            }

        condition = getattr(asset, "condition", None)

        if condition is None:
            condition = getattr(
                getattr(asset, "portion", None),
                "condition",
                "UNKNOWN"
            )

        if condition in ("EXCELLENT", "GOOD"):
            options.append({
                "action": "REUSE",
                "reason": "The asset condition may support continued use.",
                "review_required": True,
            })

        if condition in ("FAIR", "POOR"):
            options.append({
                "action": "REPAIR",
                "reason": "A condition assessment may identify repair options.",
                "review_required": True,
            })

        options.extend([
            {
                "action": "REFURBISH",
                "reason": "Consider refurbishment after technical inspection.",
                "review_required": True,
            },
            {
                "action": "DONATE",
                "reason": "Consider donation if internal reuse is unsuitable.",
                "review_required": True,
            },
            {
                "action": "RECYCLE",
                "reason": "Consider recycling when reuse is not feasible.",
                "review_required": True,
            },
        ])

        return {
            "status": "REVIEW_REQUIRED",
            "options": options,
            "reason": "Suggestions require custodian review and verified evidence.",
        }

