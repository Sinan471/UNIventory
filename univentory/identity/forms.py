import json

from django import forms
from django.utils.translation import gettext_lazy as _

from identity.models import AppUser, Category, Department, Location, Role


class ReferenceForm(forms.ModelForm):
    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)


class DepartmentForm(ReferenceForm):
    class Meta:
        model = Department
        fields = ["code", "name", "name_ar"]


class LocationForm(ReferenceForm):
    class Meta:
        model = Location
        fields = ["code", "name", "name_ar", "site", "campus", "building", "room", "department"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.active()
        self.fields["department"].required = False


class CategoryForm(ReferenceForm):
    subcategories_text = forms.CharField(
        label=_("Subcategories"), required=False, help_text=_("One per line."), widget=forms.Textarea(attrs={"rows": 3})
    )
    spec_schema_text = forms.CharField(
        label=_("Specification fields (JSON)"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "class": "mono"}),
        help_text=_('Example: [{"key": "ram_gb", "label": "RAM", "type": "integer", "unit": "GB"}]'),
    )

    class Meta:
        model = Category
        fields = ["code", "name", "name_ar", "description", "illustration"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["subcategories_text"].initial = "\n".join(self.instance.subcategories)
            self.fields["spec_schema_text"].initial = json.dumps(self.instance.spec_schema, indent=2)

    def clean_spec_schema_text(self):
        raw = self.cleaned_data.get("spec_schema_text", "").strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(_("Enter valid JSON.")) from exc
        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.subcategories = [
            line.strip() for line in self.cleaned_data.get("subcategories_text", "").splitlines() if line.strip()
        ]
        instance.spec_schema = self.cleaned_data.get("spec_schema_text") or []
        if commit:
            instance.save()
        return instance


class GrantRoleForm(forms.Form):
    role = forms.ModelChoiceField(queryset=Role.objects.all(), label=_("Role"))
    department = forms.ModelChoiceField(
        queryset=Department.objects.active(), required=False, label=_("Department scope")
    )
    effective_to = forms.DateTimeField(
        required=False, label=_("Ends (optional)"), widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    reason = forms.CharField(max_length=255, required=False, label=_("Reason"))


class RevokeForm(forms.Form):
    reason = forms.CharField(max_length=255, label=_("Reason for revoking"))


class AccountStatusForm(forms.Form):
    active = forms.BooleanField(required=False)
    reason = forms.CharField(max_length=255, label=_("Reason"))


class PersonSearchForm(forms.Form):
    q = forms.CharField(required=False, label=_("Search people"))

    def filter(self, qs):
        if self.is_valid() and self.cleaned_data["q"]:
            q = self.cleaned_data["q"]
            qs = qs.filter(display_name__icontains=q) | qs.filter(email__icontains=q)
        return qs


def dev_users():
    return AppUser.objects.filter(identity_issuer="dev-test", is_active=True).order_by("display_name")
