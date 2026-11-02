from app.payments import service
from app.payments.api import bp


@bp.cli.command("cancel-stale-payments")
def cancel_stale_payments() -> None:
    """Cancel payments still pending after 24 hours."""
    service.cancel_stale_payments()
