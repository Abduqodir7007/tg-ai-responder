from django import forms

from .models import Account, ProviderConfig


class AccountForm(forms.ModelForm):
    api_hash = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="From my.telegram.org. Leave empty to keep the stored value.",
    )

    class Meta:
        model = Account
        fields = [
            "name",
            "phone",
            "api_id",
            "api_hash",
            "auto_reply_enabled",
            "provider",
            "model_override",
            "persona_prompt",
            "chat_filter_mode",
            "allow_groups",
        ]

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("api_hash") and not (self.instance and self.instance.api_hash_encrypted):
            self.add_error("api_hash", "api_hash is required")
        return cleaned

    def save(self, commit=True):
        account = super().save(commit=False)
        api_hash = self.cleaned_data.get("api_hash")
        if api_hash:
            account.set_api_hash(api_hash.strip())
        if commit:
            account.save()
        return account


class ProviderConfigForm(forms.ModelForm):
    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Stored encrypted. Leave empty to keep the current key.",
    )

    class Meta:
        model = ProviderConfig
        fields = ["provider", "api_key", "model", "enabled"]

    def save(self, commit=True):
        config = super().save(commit=False)
        api_key = self.cleaned_data.get("api_key")
        if api_key:
            config.set_api_key(api_key.strip())
        if commit:
            config.save()
        return config


class PhoneForm(forms.Form):
    phone = forms.CharField(max_length=32, help_text="International format, e.g. +998901234567")


class CodeForm(forms.Form):
    code = forms.CharField(max_length=10)


class PasswordForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput)
