
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



def assess(portion, open_demand=0):
    """Compare the nine documented next actions for one portion (AI-07, AI-08).

    Hard rules come first: an unsafe or restricted item is never suggested for
    reuse or transfer, and data-bearing or hazardous items need specialist
    clearance before any final action. Each option says whether it is
    suggested, possible, or blocked, and why. This is advice only.
    """
    asset = portion.asset
    condition = portion.condition
    safety = portion.safety_state
    good = condition in ("GOOD", "EXCELLENT")
    fair = condition in ("FAIR", "POOR")
    unknown = condition in ("", "UNKNOWN", None)
    unsafe = safety != "CLEARED"
    special = asset.is_data_bearing or asset.is_hazardous or asset.is_regulated
    restricted = asset.has_restriction and not asset.release_rights_confirmed
    rows = []

    def add(action, verdict, reason):
        rows.append({"action": action, "verdict": verdict, "reason": reason})

    if unsafe:
        add("Keep in use or reuse", "blocked", "Safety is not cleared; it cannot be reused until maintenance verifies it.")
        add("Internal transfer", "blocked", "Unsafe or uncleared items cannot be reserved or dispatched.")
    else:
        add("Keep in use or reuse", "suggested" if good else "possible",
            "Condition supports continued use." if good else "Usable, but check condition first.")
        add("Internal transfer", "suggested" if good and open_demand else "possible",
            f"{open_demand} open request(s) in this category." if open_demand else "No open request in this category yet; list it on the exchange.")
    add("Repair", "suggested" if (fair or unsafe) else "not needed",
        "Condition or a safety block points to an inspection and repair estimate." if (fair or unsafe) else "No fault recorded.")
    add("Refurbish", "possible" if fair else "not needed", "Cosmetic or wear issues could be refurbished after inspection." if fair else "Condition is already good.")
    if special:
        for name in ("Donation", "Recover components", "Recycling", "Disposal"):
            add(name, "needs evidence", "Data-bearing, hazardous or regulated: specialist clearance is required first.")
    elif restricted:
        for name in ("Donation", "Recover components", "Recycling", "Disposal"):
            add(name, "blocked", "Ownership or release rights are not confirmed.")
    else:
        add("Donation", "possible" if not unsafe else "blocked",
            "If no internal demand appears, an external recipient could reuse it." if not unsafe else "Unsafe items are not donated.")
        add("Recover components", "possible" if fair else "not needed", "Useful parts can be recovered from a failed unit." if fair else "Whole item is still usable.")
        add("Recycling", "possible", "Allowed after approval; counts only with a recycling certificate.")
        add("Disposal", "last resort", "Only when reuse, repair, donation and recycling are ruled out.")
    add("Retire", "possible", "Removes it from usable stock but keeps custody and history.")
    status = "Insufficient evidence" if unknown else ("Needs review" if unsafe or special else "Sufficient evidence")
    return {"rows": rows, "status": status,
            "missing": [m for m, flag in (("condition", unknown), ("repair cost estimate", fair or unsafe),
                                          ("carbon factor", True)) if flag]}
