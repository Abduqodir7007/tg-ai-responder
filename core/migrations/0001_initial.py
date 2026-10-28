
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Account',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('phone', models.CharField(blank=True, default='', max_length=32)),
                ('api_id', models.PositiveIntegerField()),
                ('api_hash_encrypted', models.TextField(blank=True, default='')),
                ('session_encrypted', models.TextField(blank=True, default='')),
                ('phone_code_hash', models.CharField(blank=True, default='', max_length=255)),
                ('telegram_user_id', models.BigIntegerField(blank=True, null=True)),
                ('telegram_username', models.CharField(blank=True, default='', max_length=64)),
                ('status', models.CharField(choices=[('new', 'New'), ('code_sent', 'Code sent'), ('password_needed', '2FA password needed'), ('connected', 'Connected'), ('disconnected', 'Disconnected'), ('error', 'Error')], default='new', max_length=20)),
                ('last_error', models.TextField(blank=True, default='')),
                ('auto_reply_enabled', models.BooleanField(default=False)),
                ('provider', models.CharField(blank=True, choices=[('claude', 'Claude (Anthropic)'), ('gemini', 'Gemini (Google)')], default='', max_length=16)),
                ('model_override', models.CharField(blank=True, default='', max_length=100)),
                ('persona_prompt', models.TextField(blank=True, default='')),
                ('chat_filter_mode', models.CharField(choices=[('all', 'All private chats'), ('whitelist', 'Only whitelisted chats'), ('blacklist', 'All except blacklisted chats')], default='all', max_length=16)),
                ('allow_groups', models.BooleanField(default=False)),
                ('bootstrap_status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('done', 'Done'), ('failed', 'Failed')], default='pending', max_length=16)),
                ('bootstrapped_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='GlobalSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kill_switch', models.BooleanField(default=False)),
                ('default_provider', models.CharField(choices=[('claude', 'Claude (Anthropic)'), ('gemini', 'Gemini (Google)')], default='claude', max_length=16)),
                ('burst_window_seconds', models.PositiveIntegerField(default=20)),
                ('reply_delay_min_seconds', models.PositiveIntegerField(default=4)),
                ('reply_delay_max_seconds', models.PositiveIntegerField(default=15)),
                ('min_seconds_between_replies', models.PositiveIntegerField(default=30)),
                ('max_replies_per_hour', models.PositiveIntegerField(default=20)),
                ('recent_messages_count', models.PositiveIntegerField(default=8)),
                ('max_images_in_reply', models.PositiveIntegerField(default=3)),
                ('resummarize_every_n_messages', models.PositiveIntegerField(default=20)),
                ('context_refresh_hours', models.PositiveIntegerField(default=24)),
                ('summary_chunk_size', models.PositiveIntegerField(default=60)),
                ('summary_max_messages', models.PositiveIntegerField(default=300)),
                ('bootstrap_dialog_limit', models.PositiveIntegerField(default=50)),
                ('bootstrap_messages_per_dialog', models.PositiveIntegerField(default=200)),
                ('reply_max_tokens', models.PositiveIntegerField(default=800)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Global settings',
                'verbose_name_plural': 'Global settings',
            },
        ),
        migrations.CreateModel(
            name='ProviderConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(choices=[('claude', 'Claude (Anthropic)'), ('gemini', 'Gemini (Google)')], max_length=16, unique=True)),
                ('api_key_encrypted', models.TextField(blank=True, default='')),
                ('model', models.CharField(blank=True, default='', max_length=100)),
                ('enabled', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='Chat',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telegram_chat_id', models.BigIntegerField()),
                ('title', models.CharField(blank=True, default='', max_length=255)),
                ('username', models.CharField(blank=True, default='', max_length=64)),
                ('chat_type', models.CharField(choices=[('private', 'Private'), ('group', 'Group'), ('channel', 'Channel')], default='private', max_length=16)),
                ('is_bot', models.BooleanField(default=False)),
                ('auto_reply_enabled', models.BooleanField(default=True)),
                ('list_status', models.CharField(choices=[('none', 'Not listed'), ('whitelisted', 'Whitelisted'), ('blacklisted', 'Blacklisted')], default='none', max_length=16)),
                ('messages_since_summary', models.PositiveIntegerField(default=0)),
                ('last_message_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chats', to='core.account')),
            ],
        ),
        migrations.CreateModel(
            name='ContactContext',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, default='', max_length=255)),
                ('relationship', models.CharField(blank=True, default='', max_length=255)),
                ('language', models.CharField(blank=True, default='', max_length=64)),
                ('tone', models.CharField(blank=True, default='', max_length=255)),
                ('topics', models.JSONField(blank=True, default=list)),
                ('summary', models.TextField(blank=True, default='')),
                ('facts', models.JSONField(blank=True, default=dict)),
                ('open_tasks', models.JSONField(blank=True, default=list)),
                ('open_questions', models.JSONField(blank=True, default=list)),
                ('last_summarized_msg_id', models.BigIntegerField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('chat', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='context', to='core.chat')),
            ],
        ),
        migrations.CreateModel(
            name='MessageLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('telegram_msg_id', models.BigIntegerField(blank=True, null=True)),
                ('direction', models.CharField(choices=[('in', 'Incoming'), ('out', 'Outgoing')], max_length=4)),
                ('media_type', models.CharField(choices=[('text', 'Text'), ('photo', 'Photo'), ('video', 'Video'), ('video_note', 'Video note'), ('voice', 'Voice'), ('audio', 'Audio'), ('document', 'Document'), ('sticker', 'Sticker'), ('other', 'Other')], default='text', max_length=16)),
                ('text', models.TextField(blank=True, default='')),
                ('transcript', models.TextField(blank=True, default='')),
                ('media_path', models.CharField(blank=True, default='', max_length=500)),
                ('media_mime', models.CharField(blank=True, default='', max_length=100)),
                ('provider', models.CharField(blank=True, default='', max_length=16)),
                ('input_tokens', models.PositiveIntegerField(default=0)),
                ('output_tokens', models.PositiveIntegerField(default=0)),
                ('status', models.CharField(choices=[('received', 'Received'), ('queued', 'Queued for reply'), ('replied', 'Replied'), ('skipped', 'Skipped'), ('pending_send', 'Pending send'), ('sent', 'Sent'), ('failed', 'Failed')], default='received', max_length=16)),
                ('source', models.CharField(choices=[('telegram', 'Contact'), ('owner', 'Owner (manual)'), ('ai', 'AI'), ('bootstrap', 'Bootstrap history')], default='telegram', max_length=16)),
                ('error', models.TextField(blank=True, default='')),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.account')),
                ('chat', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.chat')),
                ('reply_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='replies', to='core.messagelog')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddConstraint(
            model_name='chat',
            constraint=models.UniqueConstraint(fields=('account', 'telegram_chat_id'), name='uniq_account_chat'),
        ),
        migrations.AddIndex(
            model_name='messagelog',
            index=models.Index(fields=['chat', 'direction', 'created_at'], name='core_messag_chat_id_e8963e_idx'),
        ),
        migrations.AddConstraint(
            model_name='messagelog',
            constraint=models.UniqueConstraint(condition=models.Q(('telegram_msg_id__isnull', False)), fields=('chat', 'telegram_msg_id'), name='uniq_chat_msg'),
        ),
    ]
