from uuid import UUID

from orchestrator.domain.base import SubscriptionModel
from orchestrator.services.subscriptions import _generate_etag, build_domain_model, build_extended_domain_model
from orchestrator.utils.redis import from_redis


async def get_subscription_dict(subscription_id: UUID, inject_inuseby: bool = True) -> tuple[dict, str]:
    """Helper function to get subscription dict by uuid from db or cache."""

    if cached_model := from_redis(subscription_id):
        return cached_model  # type: ignore

    subscription_model = SubscriptionModel.from_subscription(subscription_id)

    if not inject_inuseby:
        subscription = build_domain_model(subscription_model)
    else:
        subscription = build_extended_domain_model(subscription_model)
    etag = _generate_etag(subscription)
    return subscription, etag
