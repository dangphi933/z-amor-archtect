# z_engine.py
def compute_z_pressure(
    loss_component: float,
    giveback_component: float,
    account_component: float,
    margin_component: float,
    weights: dict
) -> float:
    ...
def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def normalize_weights(weights: dict) -> dict:
    total = sum(weights.values())
    if total == 0:
        raise ValueError("Weight sum cannot be zero")
    return {k: v / total for k, v in weights.items()}


def compute_z_pressure(
    loss_component: float,
    giveback_component: float,
    account_component: float,
    margin_component: float,
    weights: dict,
    cap: float = 1.5
) -> float:
    # Clamp components
    L = clamp01(loss_component)
    G = clamp01(giveback_component)
    A = clamp01(account_component)
    M = clamp01(margin_component)

    # Normalize weights
    w = normalize_weights(weights)

    vector = (
        w["daily_loss"] * L +
        w["giveback"]   * G +
        w["account"]    * A +
        w["margin"]     * M
    )

    return min(cap, vector)