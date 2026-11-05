from unittest.mock import patch

import pytest

from backend.app.core.config import Settings
from backend.app.services.review import ContractReviewService
from backend.app.services.model_gateway import cloud_error_chain


@pytest.mark.parametrize('host,model,enabled', [
    ('https://api.deepseek.com', 'deepseek-flash', True),
    ('https://api.deepseek.com/v1', 'deepseek-flash', True),
    ('https://other.invalid', 'deepseek-flash', False),
    ('https://api.deepseek.com', 'another-model', False),
])
def test_review_thinking_is_provider_scoped(host, model, enabled):
    settings = Settings(chat_base_url=host, chat_model=model, chat_api_key='sk-test-diagnostic',
                        embedding_base_url='https://unused.invalid', embedding_model='unused',
                        embedding_api_key='', chroma_path='.runtime/unused')
    with patch('backend.app.services.review.ChatOpenAI') as chat:
        service = ContractReviewService(settings=settings)
        try:
            args = chat.call_args.kwargs
            assert args.get('extra_body') == ({'thinking': {'type': 'enabled'}} if enabled else None)
            assert args.get('reasoning_effort') == ('high' if enabled else None)
            assert args['max_retries'] == 0
        finally:
            service.close()


def test_error_chain_omits_sensitive_messages_and_handles_cycles():
    outer = RuntimeError('secret contract and key')
    inner = TimeoutError('private payload')
    outer.__cause__ = inner
    inner.__cause__ = outer
    assert cloud_error_chain(outer) == 'RuntimeError -> TimeoutError'
