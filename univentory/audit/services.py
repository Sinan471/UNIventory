import json
from dataclasses import asdict
from django.core.serializers.json import DjangoJSONEncoder
from .models import AuditLog


class AuditService:
    is_test_adapter = False

    def record(self, entry):
        values = asdict(entry)
        values["before"] = json.loads(json.dumps(values["before"], cls=DjangoJSONEncoder))
        values["after"] = json.loads(json.dumps(values["after"], cls=DjangoJSONEncoder))
        return AuditLog.objects.create(**values)

    def record_denied(self, entry):
        return self.record(entry)
