from django.core.management.base import BaseCommand

from pipeline.digest_email import send_digest


class Command(BaseCommand):
    help = 'Send the pipeline digest email. With --to it goes to those addresses only; otherwise to every active digest recipient.'

    def add_arguments(self, parser):
        parser.add_argument('--to', nargs='+', help='Send only to these addresses (a test)')

    def handle(self, *args, **opts):
        for email, result in send_digest(opts['to']):
            self.stdout.write('%s: %s' % (email, result))
