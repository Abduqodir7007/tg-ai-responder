import asyncio
from getpass import getpass

from django.core.management.base import BaseCommand, CommandError
from telethon.errors import SessionPasswordNeededError

from core.models import Account
from core.telegram_login import finalize, make_client


class Command(BaseCommand):
    help = "Log a Telegram account in by scanning a QR code (Settings > Devices > Link Desktop Device)"

    def add_arguments(self, parser):
        parser.add_argument("account_id", type=int)
        parser.add_argument("--timeout", type=int, default=120)

    def handle(self, *args, **options):
        account = Account.objects.filter(pk=options["account_id"]).first()
        if account is None:
            raise CommandError("Account not found")
        me, session = asyncio.run(self.flow(account, options["timeout"]))
        finalize(account, me, session)
        self.stdout.write(self.style.SUCCESS(f"Account {account.pk} connected as {me.id}"))

    async def flow(self, account: Account, timeout: int):
        client = make_client(account)
        await client.connect()
        try:
            qr = await client.qr_login()
            while True:
                self.stdout.write("Open this link on a logged-in device or render it as a QR code:")
                self.stdout.write(qr.url)
                try:
                    me = await qr.wait(timeout)
                    break
                except SessionPasswordNeededError:
                    me = await client.sign_in(password=getpass("2FA password: "))
                    break
                except asyncio.TimeoutError:
                    await qr.recreate()
            return me, client.session.save()
        finally:
            await client.disconnect()
