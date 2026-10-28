import asyncio

from django.core.management.base import BaseCommand

from listener.service import ListenerService


class Command(BaseCommand):
    help = "Run the single long-lived Telethon listener for all connected accounts"

    def handle(self, *args, **options):
        self.stdout.write("Starting Telegram listener")
        try:
            asyncio.run(ListenerService().run())
        except KeyboardInterrupt:
            self.stdout.write("Listener stopped")
