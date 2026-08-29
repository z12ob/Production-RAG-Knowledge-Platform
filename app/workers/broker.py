import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings

BROKER_NAMESPACE = "rag-platform"
DOCUMENT_PROCESSING_QUEUE = "document-processing"

settings = get_settings()
broker = RedisBroker(  # type: ignore[no-untyped-call]
    url=settings.redis_url.unicode_string(),
    namespace=BROKER_NAMESPACE,
)
dramatiq.set_broker(broker)
