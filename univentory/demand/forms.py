from django import forms
from identity.models import Department, Role
from identity.policy import AccessPolicy
from .models import ResourceRequest


class RequestForm(forms.ModelForm):
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)
    operation_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    class Meta:
        model = ResourceRequest
        fields = ["department", "title", "purpose", "specifications", "quantity", "needed_by", "urgent", "urgent_reason"]
        widgets = {"needed_by": forms.DateInput(attrs={"type": "date"}), "purpose": forms.Textarea(attrs={"rows": 3}), "specifications": forms.Textarea(attrs={"rows": 3}), "urgent_reason": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.active().filter(pk__in=AccessPolicy.departments_with_role(user, Role.REQUESTER))

    def clean(self):
        data = super().clean()
        if data.get("urgent") and not (data.get("urgent_reason") or "").strip():
            self.add_error("urgent_reason", "Explain why this request is urgent.")
        return data
