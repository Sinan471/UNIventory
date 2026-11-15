from django import forms
from django.utils.translation import gettext_lazy as _

from identity.models import Category, Department, Location
from inventory.models import Condition, Lifecycle


class CatalogueFilterForm(forms.Form):
    q = forms.CharField(required=False, label=_("Search"),
                        widget=forms.TextInput(attrs={"type": "search", "placeholder": _("Chairs, microscope, KU-2026-000012")}))
    category = forms.ModelChoiceField(queryset=Category.objects.active(), required=False, label=_("Category"),
                                      empty_label=_("All categories"))
    condition = forms.ChoiceField(required=False, label=_("Condition"),
                                  choices=[("", _("Any condition"))] + [c for c in Condition.choices if c[0] != "UNKNOWN"])
    department = forms.ModelChoiceField(queryset=Department.objects.active(), required=False, label=_("Department"),
                                        empty_label=_("All departments"))
    location = forms.ModelChoiceField(queryset=Location.objects.active(), required=False, label=_("Location"),
                                      empty_label=_("Any location"))
    availability = forms.ChoiceField(required=False, label=_("Availability"), choices=[
        ("available", _("Free units now")), ("all", _("All published listings"))])
    min_qty = forms.IntegerField(required=False, min_value=1, label=_("Minimum free quantity"))
    age = forms.ChoiceField(required=False, label=_("Asset age"), choices=[
        ("", _("Any age")), ("lt1", _("Under 1 year")), ("1to3", _("1-3 years")), ("3to5", _("3-5 years")),
        ("gt5", _("Over 5 years")), ("unknown", _("Unknown"))])
    value_min = forms.DecimalField(required=False, min_value=0, decimal_places=2, label=_("Value from (AED)"))
    value_max = forms.DecimalField(required=False, min_value=0, decimal_places=2, label=_("Value to (AED)"))
    lifecycle = forms.ChoiceField(required=False, label=_("Life-cycle state"), choices=[
        ("", _("Any state")), (Lifecycle.AVAILABLE, Lifecycle.AVAILABLE.label), (Lifecycle.IN_USE, Lifecycle.IN_USE.label)])
    sort = forms.ChoiceField(required=False, label=_("Sort by"), choices=[
        ("newest", _("Newest")), ("title", _("Title A-Z")), ("free", _("Most free units")),
        ("value_low", _("Value: low to high")), ("value_high", _("Value: high to low"))])
    view = forms.ChoiceField(required=False, choices=[("grid", "grid"), ("list", "list")], widget=forms.HiddenInput)

    ADVANCED = ("location", "min_qty", "age", "value_min", "value_max", "lifecycle")

    def params(self) -> dict:
        if not self.is_valid():
            return {"availability": "available"}
        data = {}
        for key, value in self.cleaned_data.items():
            if value in (None, ""):
                continue
            data[key] = value.pk if hasattr(value, "pk") else value
        data.setdefault("availability", "available")
        return data

    def active_filters(self) -> list[tuple[str, str]]:
        if not self.is_valid():
            return []
        out = []
        for name, value in self.cleaned_data.items():
            if name in {"sort", "view", "q"} or value in (None, ""):
                continue
            if name == "availability" and value == "available":
                continue
            field = self.fields[name]
            label = str(value)
            if isinstance(field, forms.ChoiceField) and not isinstance(field, forms.ModelChoiceField):
                label = dict(field.choices).get(value, value)
            out.append((str(field.label), str(label)))
        return out

    def advanced_open(self) -> bool:
        return self.is_valid() and any(self.cleaned_data.get(k) not in (None, "") for k in self.ADVANCED)


class ListingForm(forms.Form):
    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)
    version = forms.IntegerField(widget=forms.HiddenInput, required=False)
    title = forms.CharField(max_length=160, label=_("Listing title"))
    public_description = forms.CharField(
        label=_("Public description"), widget=forms.Textarea(attrs={"rows": 4}),
        help_text=_("Shown to all signed-in staff. Do not include prices, supplier terms or personal contact details."),
    )
    offered_quantity = forms.DecimalField(min_value=0, decimal_places=3, label=_("Offered quantity"))
    collection_info = forms.CharField(
        label=_("Collection information"), widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Building, access hours and handling notes for collection."),
    )


class ListingActionForm(forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    operation_key = forms.CharField(widget=forms.HiddenInput, required=False)
    reason = forms.CharField(max_length=255, required=False, label=_("Reason"))


class ReleaseDecisionForm(forms.Form):
    decision = forms.ChoiceField(choices=[("approved", _("Approve release")), ("returned", _("Return for changes")),
                                          ("rejected", _("Reject"))], widget=forms.RadioSelect, label=_("Decision"))
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("Reason"))
