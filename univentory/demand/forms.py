from django import forms
from django.utils import timezone
from identity.models import Category, Department, Location, Role
from identity.policy import AccessPolicy
from .models import ResourceRequest


class RequestForm(forms.ModelForm):
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)
    operation_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    class Meta:
        model = ResourceRequest
        fields = ["department", "title", "category", "quantity", "min_condition", "needed_by", "destination", "purpose",
                  "specifications", "urgent", "urgent_reason"]
        widgets = {"needed_by": forms.DateInput(attrs={"type": "date"}), "purpose": forms.Textarea(attrs={"rows": 3}), "specifications": forms.Textarea(attrs={"rows": 3}), "urgent_reason": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user, submitting=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.submitting = submitting
        departments = AccessPolicy.departments_with_role(user, Role.REQUESTER)
        self.fields["department"].queryset = Department.objects.active().filter(pk__in=departments)
        self.fields["category"].queryset = Category.objects.active()
        self.fields["destination"].queryset = Location.objects.active().filter(department_id__in=departments)
        self.fields["needed_by"].widget.attrs["min"] = timezone.localdate().isoformat()

    def clean(self):
        data = super().clean()
        if data.get("urgent") and not (data.get("urgent_reason") or "").strip():
            self.add_error("urgent_reason", "Explain why this request is urgent.")
        if data.get("needed_by") and data["needed_by"] < timezone.localdate():
            self.add_error("needed_by", "The required date cannot be in the past.")
        destination, department = data.get("destination"), data.get("department")
        if destination and department and destination.department_id != department.pk:
            self.add_error("destination", "Choose a location in the requesting department.")
        if self.submitting:
            for name, message in (("category", "Choose a category to submit."),
                                  ("needed_by", "Give the date you need the items by."),
                                  ("destination", "Choose where the items should go.")):
                if not data.get(name) and name not in self.errors:
                    self.add_error(name, message)
        return data
