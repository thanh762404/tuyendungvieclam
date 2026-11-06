from django.apps import AppConfig


class JobsConfig(AppConfig):
    name = 'jobs'

    def ready(self):
        from . import signals
