from dataclasses import dataclass

FEED = "BERI PAKAN"
HOLD = "TAHAN"


@dataclass(frozen=True)
class Decision:
    feed: bool
    reason: str

    @property
    def label(self):
        return FEED if self.feed else HOLD


def format_percent(p):
    """Indonesian percent; never shows 100% or 0% because the model is never certain."""
    if p >= 0.9995:
        return "> 99,9%"
    if 0 < p < 0.0005:
        return "< 0,1%"
    return f"{p * 100:.1f}%".replace(".", ",")


def decide(prediction):
    tau = f"{prediction.tau:.2f}".replace(".", ",")
    if prediction.label != prediction.target:
        return Decision(False, f"terdeteksi {prediction.label}, bukan target ({prediction.target})")
    if prediction.confidence < prediction.tau:
        return Decision(False, f"keyakinan {format_percent(prediction.confidence)} < τ {tau}")
    return Decision(True, f"keyakinan {format_percent(prediction.confidence)} ≥ τ {tau}")
