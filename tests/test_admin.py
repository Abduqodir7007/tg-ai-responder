import pytest
from django.urls import reverse

from core.models import ProviderConfig


@pytest.fixture
def admin_client_logged(admin_client, gs, account, chat, providers):
    return admin_client


@pytest.mark.parametrize(
    "name",
    [
        "admin:core_account_changelist",
        "admin:core_chat_changelist",
        "admin:core_messagelog_changelist",
        "admin:core_contactcontext_changelist",
        "admin:core_providerconfig_changelist",
    ],
)
def test_admin_pages_render(admin_client_logged, name):
    assert admin_client_logged.get(reverse(name)).status_code == 200


def test_provider_keys_are_masked_in_admin(admin_client_logged):
    content = admin_client_logged.get(reverse("admin:core_providerconfig_changelist")).content.decode()

    assert "sk-ant-test-claude-key" not in content
    assert "sk-a********-key" in content


def test_provider_key_kept_when_left_blank(admin_client_logged, providers):
    config = providers["claude"]
    url = reverse("admin:core_providerconfig_change", args=[config.pk])

    response = admin_client_logged.post(url, {"provider": "claude", "api_key": "", "model": "claude-opus-5-5",
                                              "enabled": "on"})

    assert response.status_code == 302
    config = ProviderConfig.objects.get(pk=config.pk)
    assert config.get_api_key() == "sk-ant-test-claude-key"
    assert config.model == "claude-opus-5-5"


def test_connect_wizard_renders_phone_step(admin_client_logged, account):
    response = admin_client_logged.get(reverse("admin:core_account_connect", args=[account.pk]))

    assert response.status_code == 200
    assert "Kod yuborish" in response.content.decode()


def test_global_settings_redirects_to_singleton(admin_client_logged):
    response = admin_client_logged.get(reverse("admin:core_globalsettings_changelist"))

    assert response.status_code == 302
    assert admin_client_logged.get(response.url).status_code == 200


def test_change_pages_render(admin_client_logged, account, chat):
    assert admin_client_logged.get(reverse("admin:core_account_change", args=[account.pk])).status_code == 200
    assert admin_client_logged.get(reverse("admin:core_chat_change", args=[chat.pk])).status_code == 200
    assert admin_client_logged.get(reverse("admin:core_account_add")).status_code == 200
